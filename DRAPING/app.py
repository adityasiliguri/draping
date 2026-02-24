import os
import io
import sqlite3
from datetime import datetime, timedelta

from dotenv import load_dotenv

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
    send_from_directory,
    session,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from sqlalchemy import or_
from sqlalchemy.orm import aliased
from sqlalchemy.exc import IntegrityError

import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')

db_uri = (
    os.environ.get('DATABASE_URL')
    or os.environ.get('SQLALCHEMY_DATABASE_URI')
    or 'sqlite:///draping.db'
)
if db_uri.startswith('postgres://'):
    db_uri = 'postgresql://' + db_uri[len('postgres://'):]
app.config['SQLALCHEMY_DATABASE_URI'] = db_uri

app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', os.path.join(app.root_path, 'uploads'))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

IMAGE_SUBFOLDER = 'images'
VOICE_SUBFOLDER = 'voices'
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}
VOICE_EXTENSIONS = {"mp3", "wav", "m4a"}

INCH_TO_CM = 2.54

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

IMAGE_FOLDER = os.path.join(app.config['UPLOAD_FOLDER'], IMAGE_SUBFOLDER)
VOICE_FOLDER = os.path.join(app.config['UPLOAD_FOLDER'], VOICE_SUBFOLDER)

for folder in (IMAGE_FOLDER, VOICE_FOLDER):
    if not os.path.exists(folder):
        os.makedirs(folder)

db = SQLAlchemy(app)
 # migrate = Migrate(app, db)

# Models
class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120))
    insta_id = db.Column(db.String(120))
    address = db.Column(db.Text)
    notes = db.Column(db.Text)
    jobs = db.relationship('Job', backref='customer', lazy=True)
    measurements = db.relationship('CustomerMeasurement', backref='customer', lazy=True)

    __table_args__ = (db.UniqueConstraint('first_name', 'last_name', 'phone', name='unique_customer'),)


class DressCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    dress_types = db.relationship('DressType', backref='category', lazy=True)

class DressType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    measurement_params = db.relationship('MeasurementParam', backref='dress_type', lazy=True)
    category_id = db.Column(db.Integer, db.ForeignKey('dress_category.id'))

class MeasurementParam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    dress_type_id = db.Column(db.Integer, db.ForeignKey('dress_type.id'), nullable=False)


class CustomerMeasurement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    dress_type_id = db.Column(db.Integer, db.ForeignKey('dress_type.id'), nullable=False)
    param_id = db.Column(db.Integer, db.ForeignKey('measurement_param.id'), nullable=False)
    value_inch = db.Column(db.Float, nullable=False)
    value_cm = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_number = db.Column(db.String(20), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    date_delivery = db.Column(db.DateTime)
    delivered = db.Column(db.Boolean, default=False, nullable=False)
    dresses = db.relationship('JobDress', backref='job', lazy=True)
    images = db.relationship('JobImage', backref='job', lazy=True)
    voices = db.relationship('JobVoice', backref='job', lazy=True)

class JobDress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    dress_type_id = db.Column(db.Integer, db.ForeignKey('dress_type.id'), nullable=False)
    delivered = db.Column(db.Boolean, default=False, nullable=False)
    measurements = db.relationship('JobMeasurement', backref='job_dress', lazy=True)
    order_details = db.Column(db.Text)
    date_delivery = db.Column(db.DateTime)
    dress_type = db.relationship('DressType', backref='job_dresses')

class JobMeasurement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_dress_id = db.Column(db.Integer, db.ForeignKey('job_dress.id'), nullable=False)
    param_id = db.Column(db.Integer, db.ForeignKey('measurement_param.id'), nullable=False)
    value_inch = db.Column(db.Float, nullable=False)
    value_cm = db.Column(db.Float, nullable=False)

class JobImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    filename = db.Column(db.String(120), nullable=False)

class JobVoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    filename = db.Column(db.String(120), nullable=False)

class Tailor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    notes = db.Column(db.Text)


THEME_OPTIONS = {
    'blue': {
        'label': 'White + Ink Blue',
    },
    'green': {
        'label': 'White + Deep Green',
    },
    'pink': {
        'label': 'White + Pink',
    },
}


def suffix_letters(index: int) -> str:
    """Convert 0-based index to letters: 0->A, 1->B, ... 25->Z, 26->AA."""
    index += 1
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


@app.template_filter('suffix_letters')
def suffix_letters_filter(index: int) -> str:
    return suffix_letters(int(index))


def _find_logo_relative_path() -> str | None:
    """Return the relative static path to the logo file if it exists.

    Tries common names/extensions so the user can drop in PNG or JPEG.
    """
    candidate_names = [
        'img/logo.png',
        'img/logo.jpg',
        'img/logo.jpeg',
        'img/logo.jpeg.jpeg',
    ]
    static_root = os.path.join(app.root_path, 'static')
    for rel_path in candidate_names:
        abs_path = os.path.join(static_root, rel_path)
        if os.path.exists(abs_path):
            return rel_path
    return None


def ensure_job_delivered_column():
    """Ensure the 'delivered' column exists on the job table in SQLite.

    Uses a lightweight PRAGMA/ALTER TABLE so existing data is preserved.
    """
    # Flask-SQLAlchemy resolves relative sqlite paths to the instance folder.
    # Use the engine URL to get the actual on-disk database path.
    try:
        db_path = db.engine.url.database
    except Exception:
        return
    if not db_path or not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(job)")
        cols = [row[1] for row in cur.fetchall()]
        if 'delivered' not in cols:
            cur.execute("ALTER TABLE job ADD COLUMN delivered INTEGER NOT NULL DEFAULT 0")
            conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def ensure_job_dress_delivered_column():
    """Ensure the 'delivered' column exists on the job_dress table in SQLite.

    Existing databases may not have this column; add it without losing data.
    If a legacy job-level delivered flag exists, copy it to all dresses.
    """
    try:
        db_path = db.engine.url.database
    except Exception:
        return
    if not db_path or not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(job_dress)")
        cols = [row[1] for row in cur.fetchall()]
        if 'delivered' not in cols:
            cur.execute("ALTER TABLE job_dress ADD COLUMN delivered INTEGER NOT NULL DEFAULT 0")
            # Preserve old semantics: if a job was marked delivered, mark all its dresses delivered.
            try:
                cur.execute("UPDATE job_dress SET delivered = 1 WHERE job_id IN (SELECT id FROM job WHERE delivered = 1)")
            except Exception:
                pass
            conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.context_processor
def inject_theme():
    current_theme = session.get('theme', 'blue')
    if current_theme not in THEME_OPTIONS:
        current_theme = 'blue'
    logo_path = _find_logo_relative_path()
    return {
        'current_theme': current_theme,
        'theme_options': THEME_OPTIONS,
        'logo_path': logo_path,
    }


@app.route('/theme/<name>')
def set_theme(name):
    if name in THEME_OPTIONS:
        session['theme'] = name
    return redirect(request.referrer or url_for('index'))


def inches_to_cm(value_inch: float) -> float:
    try:
        return round(float(value_inch) * INCH_TO_CM, 2)
    except (TypeError, ValueError):
        return 0.0


def allowed_file(filename: str, allowed_ext: set) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in allowed_ext
    )


@app.route('/categories')
def dress_categories_list():
    categories = DressCategory.query.order_by(DressCategory.name).all()
    return render_template('dress_categories_list.html', categories=categories)


@app.route('/categories/create', methods=['GET', 'POST'])
def dress_category_create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name:
            if DressCategory.query.filter_by(name=name).first():
                flash('Category with this name already exists.', 'danger')
            else:
                db.session.add(DressCategory(name=name))
                db.session.commit()
                flash('Category created.', 'success')
                return redirect(url_for('dress_categories_list'))
    return render_template('dress_category_form.html', category=None)


@app.route('/categories/<int:category_id>/edit', methods=['GET', 'POST'])
def dress_category_edit(category_id):
    category = DressCategory.query.get_or_404(category_id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name and name != category.name:
            if DressCategory.query.filter_by(name=name).first():
                flash('Another category with this name already exists.', 'danger')
            else:
                category.name = name
                db.session.commit()
                flash('Category updated.', 'success')
                return redirect(url_for('dress_categories_list'))
    return render_template('dress_category_form.html', category=category)


@app.route('/categories/<int:category_id>/delete', methods=['POST'])
def dress_category_delete(category_id):
    category = DressCategory.query.get_or_404(category_id)
    db.session.delete(category)
    db.session.commit()
    flash('Category deleted.', 'info')
    return redirect(url_for('dress_categories_list'))


@app.route('/')
def index():
    customer_count = Customer.query.count()
    job_count = Job.query.count()
    return render_template('index.html', customer_count=customer_count, job_count=job_count)


@app.route('/customers')
def customers_list():
    q = request.args.get('q', '').strip()
    query = Customer.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Customer.first_name.ilike(like),
                Customer.last_name.ilike(like),
                Customer.phone.ilike(like),
            )
        )
    customers = query.order_by(Customer.first_name, Customer.last_name).all()
    return render_template('customers_list.html', customers=customers, q=q)


@app.route('/customers/create', methods=['GET', 'POST'])
def customer_create():
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        insta_id = request.form.get('insta_id', '').strip()
        address = request.form.get('address', '').strip()
        notes = request.form.get('notes', '').strip()

        new_customer = Customer(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
            insta_id=insta_id,
            address=address,
            notes=notes,
        )
        db.session.add(new_customer)
        try:
            db.session.commit()
            flash('Customer created successfully.', 'success')
            return redirect(url_for('customers_list'))
        except IntegrityError:
            db.session.rollback()
            flash('Customer with same first name, last name and phone already exists.', 'danger')

    return render_template('customer_form.html', customer=None)


@app.route('/customers/<int:customer_id>/edit', methods=['GET', "POST"])
def customer_edit(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    if request.method == 'POST':
        customer.first_name = request.form.get('first_name', '').strip()
        customer.last_name = request.form.get('last_name', '').strip()
        customer.phone = request.form.get('phone', '').strip()
        customer.email = request.form.get('email', '').strip()
        customer.insta_id = request.form.get('insta_id', '').strip()
        customer.address = request.form.get('address', '').strip()
        customer.notes = request.form.get('notes', '').strip()
        try:
            db.session.commit()
            flash('Customer updated successfully.', 'success')
            return redirect(url_for('customers_list'))
        except IntegrityError:
            db.session.rollback()
            flash('Update would create duplicate customer (same name and phone).', 'danger')

    return render_template('customer_form.html', customer=customer)


@app.route('/customers/<int:customer_id>/delete', methods=['POST'])
def customer_delete(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    db.session.delete(customer)
    db.session.commit()
    flash('Customer deleted.', 'info')
    return redirect(url_for('customers_list'))


@app.route('/customers/<int:customer_id>')
def customer_detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    jobs = Job.query.filter_by(customer_id=customer.id).order_by(Job.date_created.desc()).all()
    return render_template('customer_detail.html', customer=customer, jobs=jobs)


@app.route('/customers/<int:customer_id>/measurements', methods=['GET', 'POST'])
def customer_measurements(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    dress_types = DressType.query.order_by(DressType.name).all()
    dress_type_id = request.values.get('dress_type_id', type=int)
    selected_dress_type = DressType.query.get(dress_type_id) if dress_type_id else None
    params = MeasurementParam.query.filter_by(dress_type_id=dress_type_id).all() if selected_dress_type else []

    latest_values = {}
    if selected_dress_type:
        for param in params:
            latest = CustomerMeasurement.query.filter_by(
                customer_id=customer.id,
                dress_type_id=selected_dress_type.id,
                param_id=param.id,
            ).order_by(CustomerMeasurement.created_at.desc()).first()
            if latest:
                latest_values[param.id] = latest

    if request.method == 'POST' and selected_dress_type:
        for param in params:
            field_name = f"param_{param.id}"
            value_inch_str = request.form.get(field_name)
            if value_inch_str:
                try:
                    value_inch = float(value_inch_str)
                except ValueError:
                    value_inch = 0.0
                value_cm = inches_to_cm(value_inch)
                cm = CustomerMeasurement(
                    customer_id=customer.id,
                    dress_type_id=selected_dress_type.id,
                    param_id=param.id,
                    value_inch=value_inch,
                    value_cm=value_cm,
                )
                db.session.add(cm)
        db.session.commit()
        flash('Measurements saved for customer.', 'success')
        return redirect(url_for('customer_detail', customer_id=customer.id))

    return render_template(
        'customer_measurements.html',
        customer=customer,
        dress_types=dress_types,
        selected_dress_type=selected_dress_type,
        params=params,
        latest_values=latest_values,
    )


@app.route('/dress-types')
def dress_types_list():
    dress_types = DressType.query.order_by(DressType.name).all()
    categories = {c.id: c for c in DressCategory.query.all()}
    return render_template('dress_types_list.html', dress_types=dress_types, categories=categories)


@app.route('/dress-types/create', methods=['GET', 'POST'])
def dress_type_create():
    categories = DressCategory.query.order_by(DressCategory.name).all()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category_id = request.form.get('category_id', type=int)
        if name:
            if DressType.query.filter_by(name=name).first():
                flash('Dress type with this name already exists.', 'danger')
            else:
                db.session.add(DressType(name=name, category_id=category_id))
                db.session.commit()
                flash('Dress type created.', 'success')
                return redirect(url_for('dress_types_list'))
    return render_template('dress_type_form.html', dress_type=None, categories=categories)


@app.route('/dress-types/<int:dress_type_id>/edit', methods=['GET', 'POST'])
def dress_type_edit(dress_type_id):
    dress_type = DressType.query.get_or_404(dress_type_id)
    categories = DressCategory.query.order_by(DressCategory.name).all()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category_id = request.form.get('category_id', type=int)
        if name and name != dress_type.name:
            if DressType.query.filter_by(name=name).first():
                flash('Another dress type with this name already exists.', 'danger')
            else:
                dress_type.name = name
        dress_type.category_id = category_id
        db.session.commit()
        flash('Dress type updated.', 'success')
        return redirect(url_for('dress_types_list'))
    return render_template('dress_type_form.html', dress_type=dress_type, categories=categories)


@app.route('/dress-types/<int:dress_type_id>/delete', methods=['POST'])
def dress_type_delete(dress_type_id):
    dress_type = DressType.query.get_or_404(dress_type_id)
    db.session.delete(dress_type)
    db.session.commit()
    flash('Dress type deleted.', 'info')
    return redirect(url_for('dress_types_list'))


@app.route('/dress-types/<int:dress_type_id>/params', methods=['GET', 'POST'])
def measurement_params(dress_type_id):
    dress_type = DressType.query.get_or_404(dress_type_id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name:
            param = MeasurementParam(name=name, dress_type_id=dress_type.id)
            db.session.add(param)
            db.session.commit()
            flash('Measurement parameter added.', 'success')
            return redirect(url_for('measurement_params', dress_type_id=dress_type.id))

    params = MeasurementParam.query.filter_by(dress_type_id=dress_type.id).order_by(MeasurementParam.name).all()
    return render_template('measurement_params.html', dress_type=dress_type, params=params)


@app.route('/measurement-params/<int:param_id>/delete', methods=['POST'])
def measurement_param_delete(param_id):
    param = MeasurementParam.query.get_or_404(param_id)
    dress_type_id = param.dress_type_id
    db.session.delete(param)
    db.session.commit()
    flash('Measurement parameter deleted.', 'info')
    return redirect(url_for('measurement_params', dress_type_id=dress_type_id))


def generate_job_number() -> str:
    # Simple sequential job numbers: 1, 2, 3, ...
    # Existing non-numeric job numbers are ignored for sequencing.
    numeric_job_numbers = [
        int(j.job_number)
        for j in Job.query.with_entities(Job.job_number).all()
        if j.job_number and str(j.job_number).isdigit()
    ]
    next_number = (max(numeric_job_numbers) + 1) if numeric_job_numbers else 1

    # Ensure uniqueness even if some numbers were deleted/edited.
    while Job.query.filter_by(job_number=str(next_number)).first() is not None:
        next_number += 1
    return str(next_number)


@app.route('/jobs')
def jobs_list():
    show = request.args.get('show', 'open')
    jobs = Job.query.order_by(Job.date_created.desc()).all()
    return render_template('jobs_list.html', jobs=jobs, show=show)


@app.route('/jobs/create', methods=['GET', 'POST'])
def job_create():
    customers = Customer.query.order_by(Customer.first_name, Customer.last_name).all()
    selected_customer_id = request.args.get('customer_id', type=int)
    if request.method == 'POST':
        customer_id = int(request.form.get('customer_id'))
        job_number = request.form.get('job_number') or generate_job_number()
        date_delivery_str = request.form.get('date_delivery')
        date_delivery = datetime.strptime(date_delivery_str, '%Y-%m-%d') if date_delivery_str else None

        job = Job(
            customer_id=customer_id,
            job_number=job_number,
            date_delivery=date_delivery,
        )
        db.session.add(job)
        db.session.commit()
        flash('Job created. You can now add dresses and measurements.', 'success')
        return redirect(url_for('job_detail', job_id=job.id))

    suggested_job_number = generate_job_number()
    return render_template('job_form.html', customers=customers, suggested_job_number=suggested_job_number, selected_customer_id=selected_customer_id)


@app.route('/customers/quick-create', methods=['POST'])
def customer_quick_create():
    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    phone = request.form.get('phone', '').strip()
    email = request.form.get('email', '').strip()

    new_customer = Customer(
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email,
    )
    db.session.add(new_customer)
    try:
        db.session.commit()
        flash('Customer created.', 'success')
        return redirect(url_for('job_create', customer_id=new_customer.id))
    except IntegrityError:
        db.session.rollback()
        flash('Customer with same first name, last name and phone already exists.', 'danger')
        return redirect(url_for('job_create'))


@app.route('/jobs/<int:job_id>/toggle-delivered', methods=['POST'])
def job_toggle_delivered(job_id):
    job = Job.query.get_or_404(job_id)
    job.delivered = not bool(job.delivered)
    db.session.commit()
    next_url = request.args.get('next') or request.referrer or url_for('jobs_list')
    return redirect(next_url)


@app.route('/job-dresses/<int:job_dress_id>/toggle-delivered', methods=['POST'])
def job_dress_toggle_delivered(job_dress_id):
    jd = JobDress.query.get_or_404(job_dress_id)
    jd.delivered = not bool(jd.delivered)

    # Keep legacy job.delivered in sync (job is delivered only if all dresses delivered).
    job = jd.job
    if job and job.dresses:
        job.delivered = all(bool(d.delivered) for d in job.dresses)

    db.session.commit()
    next_url = request.args.get('next') or request.referrer or url_for('jobs_list')
    return redirect(next_url)


@app.route('/jobs/<int:job_id>/edit', methods=['GET', 'POST'])
def job_edit(job_id):
    job = Job.query.get_or_404(job_id)
    customers = Customer.query.order_by(Customer.first_name, Customer.last_name).all()
    if request.method == 'POST':
        job.customer_id = int(request.form.get('customer_id'))
        job.job_number = request.form.get('job_number', job.job_number)
        date_delivery_str = request.form.get('date_delivery')
        job.date_delivery = datetime.strptime(date_delivery_str, '%Y-%m-%d') if date_delivery_str else None
        db.session.commit()
        flash('Job updated.', 'success')
        return redirect(url_for('jobs_list'))
    return render_template('job_edit.html', job=job, customers=customers)


@app.route('/jobs/<int:job_id>/delete', methods=['POST'])
def job_delete(job_id):
    job = Job.query.get_or_404(job_id)

    for jd in job.dresses:
        JobMeasurement.query.filter_by(job_dress_id=jd.id).delete()
        db.session.delete(jd)

    JobImage.query.filter_by(job_id=job.id).delete()
    JobVoice.query.filter_by(job_id=job.id).delete()

    db.session.delete(job)
    db.session.commit()
    flash('Job deleted.', 'info')
    return redirect(url_for('jobs_list'))


@app.route('/jobs/<int:job_id>')
def job_detail(job_id):
    job = Job.query.get_or_404(job_id)
    dresses = JobDress.query.filter_by(job_id=job.id).all()
    dress_types = DressType.query.order_by(DressType.name).all()

    dress_measurements = {}
    for d in dresses:
        rows = []
        measurements = JobMeasurement.query.filter_by(job_dress_id=d.id).all()
        for m in measurements:
            param = MeasurementParam.query.get(m.param_id)
            rows.append({
                'name': param.name if param else str(m.param_id),
                'inch': m.value_inch,
                'cm': m.value_cm,
            })
        dress_measurements[d.id] = rows

    return render_template(
        'job_detail.html',
        job=job,
        dresses=dresses,
        dress_measurements=dress_measurements,
        dress_types=dress_types,
        image_folder=IMAGE_SUBFOLDER,
        voice_folder=VOICE_SUBFOLDER,
    )


@app.route('/jobs/<int:job_id>/add-dress', methods=['GET', 'POST'])
def job_add_dress(job_id):
    job = Job.query.get_or_404(job_id)
    categories = DressCategory.query.order_by(DressCategory.name).all()
    category_id = request.values.get('category_id', type=int)
    if category_id:
        dress_types = DressType.query.filter_by(category_id=category_id).order_by(DressType.name).all()
    else:
        dress_types = DressType.query.order_by(DressType.name).all()
    dress_type_id = request.values.get('dress_type_id', type=int)
    selected_dress_type = DressType.query.get(dress_type_id) if dress_type_id else None
    params = MeasurementParam.query.filter_by(dress_type_id=dress_type_id).all() if selected_dress_type else []

    latest_values = {}
    if selected_dress_type:
        selected_dress_name = selected_dress_type.name
        for param in params:
            param_name = param.name

            dt_old = aliased(DressType)
            mp_old = aliased(MeasurementParam)
            latest_job_row = (
                db.session.query(JobMeasurement, Job.date_created)
                .join(JobDress, JobMeasurement.job_dress_id == JobDress.id)
                .join(Job, JobDress.job_id == Job.id)
                .join(dt_old, JobDress.dress_type_id == dt_old.id)
                .join(mp_old, JobMeasurement.param_id == mp_old.id)
                .filter(
                    Job.customer_id == job.customer_id,
                    dt_old.name == selected_dress_name,
                    mp_old.name == param_name,
                )
                .order_by(Job.date_created.desc(), JobMeasurement.id.desc())
                .first()
            )
            latest_job = latest_job_row[0] if latest_job_row else None
            latest_job_date = latest_job_row[1] if latest_job_row else None

            dt_cust = aliased(DressType)
            mp_cust = aliased(MeasurementParam)
            latest_customer = (
                db.session.query(CustomerMeasurement)
                .join(dt_cust, CustomerMeasurement.dress_type_id == dt_cust.id)
                .join(mp_cust, CustomerMeasurement.param_id == mp_cust.id)
                .filter(
                    CustomerMeasurement.customer_id == job.customer_id,
                    dt_cust.name == selected_dress_name,
                    mp_cust.name == param_name,
                )
                .order_by(CustomerMeasurement.created_at.desc(), CustomerMeasurement.id.desc())
                .first()
            )

            if latest_customer and (not latest_job_date or latest_customer.created_at >= latest_job_date):
                latest_values[param.id] = latest_customer
            elif latest_job:
                latest_values[param.id] = latest_job

    if request.method == 'POST' and selected_dress_type:
        order_details = request.form.get('order_details', '').strip()
        date_delivery_str = request.form.get('date_delivery')
        date_delivery = datetime.strptime(date_delivery_str, '%Y-%m-%d') if date_delivery_str else None

        job_dress = JobDress(
            job_id=job.id,
            dress_type_id=selected_dress_type.id,
            order_details=order_details,
            date_delivery=date_delivery,
        )
        db.session.add(job_dress)
        db.session.flush()

        for param in params:
            field_name = f"param_{param.id}"
            value_inch_str = request.form.get(field_name)
            if value_inch_str:
                try:
                    value_inch = float(value_inch_str)
                except ValueError:
                    value_inch = 0.0
                value_cm = inches_to_cm(value_inch)
                jm = JobMeasurement(
                    job_dress_id=job_dress.id,
                    param_id=param.id,
                    value_inch=value_inch,
                    value_cm=value_cm,
                )
                db.session.add(jm)

                # Keep a per-customer history as well (used for "Previous" hints)
                db.session.add(
                    CustomerMeasurement(
                        customer_id=job.customer_id,
                        dress_type_id=selected_dress_type.id,
                        param_id=param.id,
                        value_inch=value_inch,
                        value_cm=value_cm,
                    )
                )

        # Optional: upload reference images / voice notes while taking measurements
        image_files = request.files.getlist('images')
        voice_files = request.files.getlist('voices')

        for file in image_files:
            if file and allowed_file(file.filename, IMAGE_EXTENSIONS):
                filename = secure_filename(file.filename)
                save_path = os.path.join(IMAGE_FOLDER, filename)
                file.save(save_path)
                db.session.add(JobImage(job_id=job.id, filename=filename))

        for file in voice_files:
            if file and allowed_file(file.filename, VOICE_EXTENSIONS):
                filename = secure_filename(file.filename)
                save_path = os.path.join(VOICE_FOLDER, filename)
                file.save(save_path)
                db.session.add(JobVoice(job_id=job.id, filename=filename))

        db.session.commit()
        flash('Dress and measurements added to job.', 'success')
        return redirect(url_for('job_detail', job_id=job.id))

    return render_template(
        'job_add_dress.html',
        job=job,
        categories=categories,
        category_id=category_id,
        dress_types=dress_types,
        selected_dress_type=selected_dress_type,
        params=params,
        latest_values=latest_values,
    )


@app.route('/jobs/<int:job_id>/upload', methods=['POST'])
def job_upload_files(job_id):
    job = Job.query.get_or_404(job_id)

    image_files = request.files.getlist('images')
    voice_files = request.files.getlist('voices')

    for file in image_files:
        if file and allowed_file(file.filename, IMAGE_EXTENSIONS):
            filename = secure_filename(file.filename)
            save_path = os.path.join(IMAGE_FOLDER, filename)
            file.save(save_path)
            db.session.add(JobImage(job_id=job.id, filename=filename))

    for file in voice_files:
        if file and allowed_file(file.filename, VOICE_EXTENSIONS):
            filename = secure_filename(file.filename)
            save_path = os.path.join(VOICE_FOLDER, filename)
            file.save(save_path)
            db.session.add(JobVoice(job_id=job.id, filename=filename))

    db.session.commit()
    flash('Files uploaded.', 'success')
    next_url = request.args.get('next') or request.form.get('next') or request.referrer
    return redirect(next_url or url_for('job_detail', job_id=job.id))


@app.route('/uploads/images/<path:filename>')
def uploaded_image(filename):
    return send_from_directory(IMAGE_FOLDER, filename)


@app.route('/uploads/voices/<path:filename>')
def uploaded_voice(filename):
    return send_from_directory(VOICE_FOLDER, filename)


def compute_pdf_delivery_date(job: Job) -> datetime | None:
    if not job.date_delivery:
        return None
    diff = job.date_delivery - job.date_created
    if diff.days < 2:
        return job.date_delivery
    return job.date_delivery - timedelta(days=2)


@app.route('/jobs/<int:job_id>/pdf')
def job_pdf(job_id):
    job = Job.query.get_or_404(job_id)
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Draw logo at top (if available)
    logo_rel = _find_logo_relative_path()
    y = height - 40
    logo_drawn = False
    logo_height = 0
    if logo_rel:
        logo_abs = os.path.join(app.root_path, 'static', logo_rel)
        if os.path.exists(logo_abs):
            try:
                logo_width = 140
                logo_height = 46
                p.drawImage(
                    logo_abs,
                    40,
                    y - logo_height,
                    width=logo_width,
                    height=logo_height,
                    preserveAspectRatio=True,
                    anchor='sw',
                )
                logo_drawn = True
            except Exception:
                logo_drawn = False

    # Title below logo with adequate spacing
    title_y = y - (logo_height + 20 if logo_drawn else 20)
    p.setFont('Helvetica-Bold', 16)
    p.drawString(40, title_y, f"Job Sheet - {job.job_number}")
    y = title_y - 25

    p.setFont('Helvetica', 10)
    cust = job.customer
    p.drawString(40, y, f"Customer: {cust.first_name} {cust.last_name}")
    y -= 15

    created_text = job.date_created.strftime('%d-%m-%Y') if job.date_created else 'N/A'
    p.drawString(40, y, f"Job Creation Date: {created_text}")
    y -= 15
    if cust.address:
        p.drawString(40, y, f"Address: {cust.address[:80]}")
        y -= 15

    display_date = compute_pdf_delivery_date(job)
    date_text = display_date.strftime('%d-%m-%Y') if display_date else 'N/A'
    p.drawString(40, y, f"Delivery Date (for tailor): {date_text}")
    y -= 25

    images = sorted(job.images, key=lambda im: im.id)
    image_idx = 0

    for jd in sorted(job.dresses, key=lambda d: d.id):
        if y < 120:
            p.showPage()
            y = height - 50
            p.setFont('Helvetica', 10)

        p.setFont('Helvetica-Bold', 12)
        p.drawString(40, y, f"Dress: {jd.dress_type.name}")
        y -= 15
        if jd.order_details:
            p.setFont('Helvetica', 10)
            p.drawString(60, y, f"Order: {jd.order_details[:90]}")
            y -= 15

        measurements = JobMeasurement.query.filter_by(job_dress_id=jd.id).all()
        if measurements:
            # Ensure enough space on page for the table; if not, new page
            needed_height = 18 + 14 * (len(measurements) + 1)
            if y - needed_height < 60:
                p.showPage()
                y = height - 50

            # Column boundaries
            x_left = 60
            x_inch = 250
            x_cm = 340
            x_right = 430
            row_h = 14

            table_top = y
            table_bottom = table_top - row_h * (len(measurements) + 1)

            # Horizontal lines (header + rows + bottom)
            p.setLineWidth(0.5)
            for i in range(len(measurements) + 2):
                line_y = table_top - row_h * i
                p.line(x_left - 10, line_y, x_right, line_y)

            # Vertical lines
            for x in (x_left - 10, x_inch - 10, x_cm - 10, x_right):
                p.line(x, table_top, x, table_bottom)

            # Header text (centered in each cell)
            p.setFont('Helvetica-Bold', 10)
            header_baseline = table_top - 10
            p.drawCentredString((x_left - 10 + x_inch - 10) / 2, header_baseline, "Measurement")
            p.drawCentredString((x_inch - 10 + x_cm - 10) / 2, header_baseline, "Inches")
            p.drawCentredString((x_cm - 10 + x_right) / 2, header_baseline, "Centimeters")

            # Rows
            p.setFont('Helvetica', 10)
            for idx, m in enumerate(measurements, start=1):
                row_top = table_top - row_h * idx
                baseline = row_top - 10
                param = MeasurementParam.query.get(m.param_id)
                # Name left-aligned in first cell
                p.drawString(x_left - 6, baseline, param.name)
                # Values centered in their cells
                p.drawCentredString((x_inch - 10 + x_cm - 10) / 2, baseline, f"{m.value_inch:.2f}")
                p.drawCentredString((x_cm - 10 + x_right) / 2, baseline, f"{m.value_cm:.2f}")

            y = table_bottom - 20
        y -= 10

        # Draw one reference image under this dress (by order)
        if image_idx < len(images):
            img = images[image_idx]
            image_idx += 1
            img_path = os.path.join(IMAGE_FOLDER, img.filename)
            if os.path.exists(img_path):
                if y < 130:
                    p.showPage()
                    y = height - 60
                p.drawImage(
                    img_path,
                    60,
                    y - 100,
                    width=200,
                    height=100,
                    preserveAspectRatio=True,
                    anchor='sw',
                )
                y -= 115

    # Any leftover images go at the end
    remaining = images[image_idx:]
    if remaining:
        if y < 180:
            p.showPage()
            y = height - 60
        p.setFont('Helvetica-Bold', 12)
        p.drawString(40, y, "Reference Images:")
        y -= 18
        for img in remaining[:3]:
            img_path = os.path.join(IMAGE_FOLDER, img.filename)
            if os.path.exists(img_path):
                if y < 120:
                    p.showPage()
                    y = height - 60
                p.drawImage(
                    img_path,
                    40,
                    y - 90,
                    width=160,
                    height=90,
                    preserveAspectRatio=True,
                    anchor='sw',
                )
                y -= 100

    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=False, download_name=f"job_{job.job_number}.pdf", mimetype='application/pdf')


@app.route('/tailors')
def tailors_list():
    tailors = Tailor.query.order_by(Tailor.name).all()
    return render_template('tailors_list.html', tailors=tailors)


@app.route('/tailors/create', methods=['GET', 'POST'])
def tailor_create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        notes = request.form.get('notes', '').strip()
        if name:
            db.session.add(Tailor(name=name, phone=phone, notes=notes))
            db.session.commit()
            flash('Tailor/Karigor added.', 'success')
            return redirect(url_for('tailors_list'))
    return render_template('tailor_form.html', tailor=None)


@app.route('/tailors/<int:tailor_id>/edit', methods=['GET', 'POST'])
def tailor_edit(tailor_id):
    tailor = Tailor.query.get_or_404(tailor_id)
    if request.method == 'POST':
        tailor.name = request.form.get('name', '').strip()
        tailor.phone = request.form.get('phone', '').strip()
        tailor.notes = request.form.get('notes', '').strip()
        db.session.commit()
        flash('Tailor/Karigor updated.', 'success')
        return redirect(url_for('tailors_list'))
    return render_template('tailor_form.html', tailor=tailor)


@app.route('/tailors/<int:tailor_id>/delete', methods=['POST'])
def tailor_delete(tailor_id):
    tailor = Tailor.query.get_or_404(tailor_id)
    db.session.delete(tailor)
    db.session.commit()
    flash('Tailor/Karigor deleted.', 'info')
    return redirect(url_for('tailors_list'))


@app.route('/bulk')
def bulk_home():
    return render_template('bulk_home.html')


@app.route('/bulk/template/customers')
def bulk_template_customers():
    buffer = io.BytesIO()
    df = pd.DataFrame(
        columns=['FirstName', 'LastName', 'Phone', 'Email', 'InstaId', 'Address', 'Notes']
    )
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Customers')
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='customers_template.xlsx')


@app.route('/bulk/template/dress-types')
def bulk_template_dress_types():
    buffer = io.BytesIO()
    df = pd.DataFrame(columns=['Name'])
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='DressTypes')
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='dress_types_template.xlsx')


@app.route('/bulk/template/measurement-params')
def bulk_template_measurement_params():
    buffer = io.BytesIO()
    df = pd.DataFrame(columns=['CategoryName', 'DressName', 'ParamName'])
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='MeasurementParams')
        # Try to enrich the template with a Dresses sheet and dropdown;
        # if anything fails, fall back to a simple three-column template.
        try:
            from openpyxl.worksheet.datavalidation import DataValidation

            wb = writer.book
            ws_params = writer.sheets['MeasurementParams']

            dresses = (
                db.session.query(DressType, DressCategory)
                .outerjoin(DressCategory, DressType.category_id == DressCategory.id)
                .order_by(DressType.name)
                .all()
            )
            ws_dresses = wb.create_sheet('Dresses')
            ws_dresses.append(['CategoryName', 'DressName'])
            for d, c in dresses:
                ws_dresses.append([c.name if c else '', d.name])

            if dresses:
                max_row = len(dresses) + 1
                dv = DataValidation(
                    type="list",
                    formula1=f"=Dresses!$B$2:$B${max_row}",
                    allow_blank=True,
                )
                ws_params.add_data_validation(dv)
                dv.add(ws_params['B2:B500'])
        except Exception:
            # Safe fallback: user still gets the basic template without dropdowns.
            pass
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='measurement_params_template.xlsx')


@app.route('/register/jobs')
def register_jobs():
    # Registers are dress-level: Open Jobs sheet contains only undelivered dresses.
    all_jobs = Job.query.order_by(Job.date_created.desc()).all()
    open_jobs = all_jobs

    def _suffix_letters(index: int) -> str:
        # 0 -> A, 1 -> B, ... 25 -> Z, 26 -> AA
        index += 1
        letters = ""
        while index > 0:
            index, rem = divmod(index - 1, 26)
            letters = chr(65 + rem) + letters
        return letters

    def _job_rows(jobs, open_only: bool = False):
        rows = []
        for j in jobs:
            cust = j.customer
            dresses = sorted(j.dresses, key=lambda d: d.id)

            # One row per dress (same JobNumber repeated), matching the Jobs list UI.
            if dresses:
                for i, jd in enumerate(dresses):
                    if open_only and bool(jd.delivered):
                        continue
                    rows.append({
                        'JobNumber': j.job_number,
                        'DressJobNumber': f"{j.job_number}{_suffix_letters(i)}" if len(dresses) > 1 else j.job_number,
                        'Dress': jd.dress_type.name,
                        'DressCount': len(dresses),
                        'CustomerName': f"{cust.first_name} {cust.last_name}",
                        'Phone': cust.phone,
                        'CreatedDate': j.date_created.strftime('%Y-%m-%d') if j.date_created else '',
                        'DeliveryDate': j.date_delivery.strftime('%Y-%m-%d') if j.date_delivery else '',
                        'Delivered': 'Yes' if jd.delivered else 'No',
                    })
            else:
                if open_only and bool(j.delivered):
                    continue
                rows.append({
                    'JobNumber': j.job_number,
                    'DressJobNumber': j.job_number,
                    'Dress': '',
                    'DressCount': 0,
                    'CustomerName': f"{cust.first_name} {cust.last_name}",
                    'Phone': cust.phone,
                    'CreatedDate': j.date_created.strftime('%Y-%m-%d') if j.date_created else '',
                    'DeliveryDate': j.date_delivery.strftime('%Y-%m-%d') if j.date_delivery else '',
                    'Delivered': 'Yes' if j.delivered else 'No',
                })
        return rows

    df_open = pd.DataFrame(_job_rows(open_jobs, open_only=True))
    df_all = pd.DataFrame(_job_rows(all_jobs, open_only=False))

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_open.to_excel(writer, index=False, sheet_name='Open Jobs')
        df_all.to_excel(writer, index=False, sheet_name='All Jobs')
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='job_register.xlsx')


@app.route('/register/customers')
def register_customers():
    customers = Customer.query.order_by(Customer.first_name, Customer.last_name).all()
    rows = []
    for c in customers:
        rows.append({
            'FirstName': c.first_name,
            'LastName': c.last_name,
            'Phone': c.phone,
            'Email': c.email,
            'InstaId': c.insta_id,
            'Address': c.address,
            'Notes': c.notes,
        })

    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Customers')
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='customer_register.xlsx')


@app.route('/bulk/upload/customers', methods=['POST'])
def bulk_upload_customers():
    file = request.files.get('file')
    if not file:
        flash('No file uploaded.', 'danger')
        return redirect(url_for('bulk_home'))
    df = pd.read_excel(file)
    for _, row in df.iterrows():
        first_name = str(row.get('FirstName', '')).strip()
        last_name = str(row.get('LastName', '')).strip()
        phone = str(row.get('Phone', '')).strip()
        if not (first_name and last_name and phone):
            continue
        if Customer.query.filter_by(first_name=first_name, last_name=last_name, phone=phone).first():
            continue
        customer = Customer(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=str(row.get('Email', '')).strip(),
            insta_id=str(row.get('InstaId', '')).strip(),
            address=str(row.get('Address', '')).strip(),
            notes=str(row.get('Notes', '')).strip(),
        )
        db.session.add(customer)
    db.session.commit()
    flash('Bulk customers uploaded.', 'success')
    return redirect(url_for('customers_list'))


@app.route('/bulk/upload/dress-types', methods=['POST'])
def bulk_upload_dress_types():
    file = request.files.get('file')
    if not file:
        flash('No file uploaded.', 'danger')
        return redirect(url_for('bulk_home'))
    df = pd.read_excel(file)
    for _, row in df.iterrows():
        name = str(row.get('Name', '')).strip()
        if not name:
            continue
        if DressType.query.filter_by(name=name).first():
            continue
        db.session.add(DressType(name=name))
    db.session.commit()
    flash('Bulk dress types uploaded.', 'success')
    return redirect(url_for('dress_types_list'))


@app.route('/bulk/upload/measurement-params', methods=['POST'])
def bulk_upload_measurement_params():
    file = request.files.get('file')
    if not file:
        flash('No file uploaded.', 'danger')
        return redirect(url_for('bulk_home'))
    df = pd.read_excel(file)

    def _clean_cell(value) -> str:
        if value is None:
            return ''
        try:
            if pd.isna(value):
                return ''
        except Exception:
            pass
        text = str(value).strip()
        return '' if text.lower() in {'nan', 'none'} else text

    added = 0
    skipped = 0
    for _, row in df.iterrows():
        category_name = _clean_cell(row.get('CategoryName', ''))
        dress_name = _clean_cell(row.get('DressName', ''))
        param_name = _clean_cell(row.get('ParamName', ''))
        if not (dress_name and param_name):
            skipped += 1
            continue

        category = None
        if category_name:
            category = DressCategory.query.filter_by(name=category_name).first()
            if not category:
                category = DressCategory(name=category_name)
                db.session.add(category)
                db.session.flush()

        # IMPORTANT:
        # DressType.name is unique globally, so always match by name first.
        # If category is provided, update the existing dress's category.
        dress_type = DressType.query.filter_by(name=dress_name).first()
        if not dress_type:
            dress_type = DressType(name=dress_name, category_id=category.id if category else None)
            db.session.add(dress_type)
            db.session.flush()
        elif category:
            dress_type.category_id = category.id

        if MeasurementParam.query.filter_by(dress_type_id=dress_type.id, name=param_name).first():
            skipped += 1
            continue
        db.session.add(MeasurementParam(dress_type_id=dress_type.id, name=param_name))
        added += 1

    try:
        db.session.commit()
        flash(f'Bulk measurement parameters uploaded. Added: {added}, Skipped: {skipped}.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Upload failed due to duplicate Dress Names or invalid data in Excel. Please check for repeated DressName with different spelling/casing and try again.', 'danger')
    return redirect(url_for('dress_types_list'))

with app.app_context():
    # Ensure existing databases get the delivered column before creating tables
    ensure_job_delivered_column()
    ensure_job_dress_delivered_column()
    db.create_all()

if __name__ == '__main__':
    # On Windows, watchdog-based reload can sometimes loop on site-packages changes.
    # Keep debug on but disable the reloader for stable local running.
    app.run(debug=True, use_reloader=False)
