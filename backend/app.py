from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from pyresparser import ResumeParser
import threading
import qrcode
from io import BytesIO
import base64
import firebase_admin
from firebase_admin import credentials, firestore
from functools import wraps
from flask_mail import Mail, Message
import stripe

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or os.urandom(24)
app.config['UPLOAD_FOLDER'] = 'static/resumes'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB limit
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('EMAIL_USER')
app.config['MAIL_PASSWORD'] = os.getenv('EMAIL_PASS')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize services
if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()
mail = Mail(app)
stripe.api_key = os.getenv('STRIPE_KEY')

# --- Helper Functions ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf', 'docx', 'doc', 'png', 'jpg', 'jpeg'}

def generate_study_plan(education, goal, skills):
    plans = {
        "1st Year": f"Focus on fundamentals: Python, Math. Start exploring {goal}",
        "2nd Year": f"Build projects using {', '.join(skills)}. Join {goal} communities",
        "3rd Year": f"Master {goal}-specific tools | LeetCode 3x/week | Mock interviews",
        "4th Year": "Job prep: Resume polishing, networking, company research",
        "Final Semester": "Finalize job applications | Practice behavioral interviews"
    }
    return plans.get(education, f"Custom plan for {goal}")

def analyze_resume(filepath):
    try:
        data = ResumeParser(filepath).get_extracted_data()
        return {
            'skills': data.get('skills', []),
            'missing_skills': ['Git'] if 'Git' not in data.get('skills', []) else [],
            'score': min(len(data.get('skills', [])) * 10, 100),
            'experience': len(data.get('experience', []))
        }
    except Exception as e:
        return {'error': str(e)}

def start_alarms(email):
    def send_reminder():
        print(f"\nALARM: Weekly reminder sent to {email}")
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_reminder, 'interval', weeks=1)
    scheduler.start()

def mentor_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'mentor_email' not in session:
            return redirect(url_for('mentor_register'))
        return f(*args, **kwargs)
    return decorated_function

def send_email(to, subject, body):
    try:
        msg = Message(subject, sender=app.config['MAIL_USERNAME'], recipients=[to])
        msg.body = body
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Email failed: {str(e)}")
        return False

# --- Student Routes ---
@app.route('/', methods=['GET', 'POST'])
def student_form():
    education_options = ["1st Year", "2nd Year", "3rd Year", "4th Year", "Final Semester"]
    interest_options = ["Software Development", "Data Science", "Cybersecurity", "AI/ML", "Design"]
    skill_options = ["Python", "Java", "JavaScript", "SQL", "C++"]

    if request.method == 'POST':
        try:
            # Handle file upload
            resume_feedback = None
            if 'resume' in request.files:
                file = request.files['resume']
                if file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    resume_feedback = analyze_resume(filepath)

            # Process form data
            data = {
                'name': request.form.get('name'),
                'email': request.form.get('email'),
                'degree': request.form.get('degree'),
                'education': request.form.get('education'),
                'goal': request.form.get('goal'),
                'interests': request.form.get('interests'),
                'skills': request.form.getlist('skills'),
                'experience': request.form.get('experience'),
                'resume_feedback': resume_feedback,
                'study_plan': generate_study_plan(
                    request.form.get('education'),
                    request.form.get('goal'),
                    request.form.getlist('skills')
                ),
                'join_date': datetime.now().isoformat()
            }

            # Store in session and Firebase
            session.update(data)
            db.collection('students').document(data['email']).set(data)
            
            # Start reminders
            threading.Thread(target=start_alarms, args=(data['email'],)).start()
            
            flash('Registration successful!', 'success')
            return redirect(url_for('dashboard'))
        
        except Exception as e:
            flash(f'Registration failed: {str(e)}', 'error')
            return redirect(request.url)

    return render_template('student_form.html',
                         education_options=education_options,
                         interest_options=interest_options,
                         skill_options=skill_options)

@app.route('/dashboard')
def dashboard():
    if not session.get('email'):
        return redirect(url_for('student_form'))
    
    # Calculate weeks left
    join_date = datetime.fromisoformat(session['join_date'])
    weeks_left = (join_date + timedelta(weeks=16) - datetime.now()).days // 7
    
    # Get available mentors
    mentors_ref = db.collection('mentors').where('status', '==', 'active').limit(5)
    mentors = [doc.to_dict() for doc in mentors_ref.stream()]
    
    return render_template('dashboard.html',
                         name=session['name'],
                         education=session['education'],
                         goal=session['goal'],
                         skills=session['skills'],
                         study_plan=session['study_plan'],
                         resume_feedback=session.get('resume_feedback'),
                         weeks_left=max(weeks_left, 0),
                         level="Beginner" if not session.get('resume_feedback') 
                              else "Intermediate" if session['resume_feedback']['score'] < 70 
                              else "Advanced",
                         mentors=mentors)

# --- Mentor Booking System ---
@app.route('/request-session', methods=['POST'])
def request_session():
    if not session.get('email'):
        return jsonify({"error": "Not logged in"}), 401
    
    try:
        mentor_email = request.form['mentor_email']
        session_data = {
            'student_email': session['email'],
            'student_name': session['name'],
            'mentor_email': mentor_email,
            'date': request.form['date'],
            'duration': int(request.form['duration']),
            'topics': request.form['topics'],
            'status': 'pending',
            'created_at': datetime.now().isoformat()
        }
        
        # Save to Firestore
        session_ref = db.collection('sessions').document()
        session_ref.set(session_data)
        
        # Notify mentor
        mentor = db.collection('mentors').document(mentor_email).get().to_dict()
        accept_url = f"{request.host_url}accept-session/{session_ref.id}"
        email_body = f"""
        New session request from {session['name']}:
        - Date: {request.form['date']}
        - Duration: {request.form['duration']} minutes
        - Topics: {request.form['topics']}
        
        Accept: {accept_url}
        """
        send_email(mentor_email, "New Session Request", email_body)
        
        return jsonify({"success": True, "message": "Request sent successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/accept-session/<session_id>')
@mentor_required
def accept_session(session_id):
    try:
        session_ref = db.collection('sessions').document(session_id)
        session_data = session_ref.get().to_dict()
        
        if session_data['mentor_email'] != session['mentor_email']:
            flash("Unauthorized action", "error")
            return redirect(url_for('mentor_dashboard'))
        
        # Create Stripe payment session
        mentor = db.collection('mentors').document(session['mentor_email']).get().to_dict()
        amount = int(mentor['hourly_charge'] * (session_data['duration'] / 60) * 100
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f"Mentorship Session with {mentor['name']}",
                    },
                    'unit_amount': amount,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('payment_success', session_id=session_id, _external=True),
            cancel_url=url_for('payment_cancel', _external=True),
            metadata={
                "session_id": session_id,
                "mentor_email": session['mentor_email'],
                "student_email": session_data['student_email']
            }
        )
        
        # Update session status
        session_ref.update({
            'status': 'accepted',
            'payment_link': checkout_session.url,
            'payment_id': checkout_session.id,
            'amount': amount / 100
        })
        
        # Notify student
        student = db.collection('students').document(session_data['student_email']).get().to_dict()
        email_body = f"""
        Your session request with {mentor['name']} has been accepted!
        Payment required: {checkout_session.url}
        """
        send_email(student['email'], "Session Accepted", email_body)
        
        return redirect(checkout_session.url)
    except Exception as e:
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('mentor_dashboard'))

@app.route('/payment-success/<session_id>')
def payment_success(session_id):
    session_ref = db.collection('sessions').document(session_id)
    session_data = session_ref.get().to_dict()
    
    if not session_data:
        flash("Invalid session", "error")
        return redirect(url_for('dashboard'))
    
    # Update payment status
    session_ref.update({'payment_status': 'completed'})
    
    # Get meeting details
    mentor = db.collection('mentors').document(session_data['mentor_email']).get().to_dict()
    
    return render_template('payment_success.html',
                         mentor_name=mentor['name'],
                         zoom_link=mentor.get('zoom_link', '#'),
                         session_date=session_data['date'])

@app.route('/payment-cancel')
def payment_cancel():
    flash("Payment was cancelled", "warning")
    return redirect(url_for('dashboard'))

# --- Mentor Routes ---
@app.route('/mentor-register', methods=['GET', 'POST'])
def mentor_register():
    if request.method == 'POST':
        try:
            # Handle QR code upload
            qr_img = None
            if 'qr_code' in request.files:
                file = request.files['qr_code']
                if file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    qr_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'qr_codes')
                    os.makedirs(qr_dir, exist_ok=True)
                    filepath = os.path.join(qr_dir, filename)
                    file.save(filepath)
                    qr_img = f"qr_codes/{filename}"

            # Generate QR if UPI ID provided
            if not qr_img and request.form.get('upi_id'):
                img = qrcode.make(f"upi://pay?pa={request.form['upi_id']}")
                buffered = BytesIO()
                img.save(buffered, format="PNG")
                qr_img = base64.b64encode(buffered.getvalue()).decode()

            mentor_data = {
                'name': request.form['name'],
                'email': request.form['email'],
                'current_role': request.form['current_role'],
                'availability': request.form.getlist('availability'),
                'hourly_charge': float(request.form['hourly_charge']),
                'notification_method': request.form['notification_method'],
                'zoom_link': request.form.get('zoom_link', ''),
                'payment_qr': qr_img,
                'registration_date': datetime.now().isoformat(),
                'status': 'active',
                'skills': request.form.getlist('skills')
            }

            db.collection('mentors').document(mentor_data['email']).set(mentor_data)
            session['mentor_email'] = mentor_data['email']
            
            flash('Registration successful!', 'success')
            return redirect(url_for('mentor_dashboard'))
        
        except Exception as e:
            flash(f'Registration failed: {str(e)}', 'error')
            return redirect(request.url)
    
    return render_template('mentor_form.html')

@app.route('/mentor-dashboard')
@mentor_required
def mentor_dashboard():
    try:
        mentor_doc = db.collection('mentors').document(session['mentor_email']).get()
        if not mentor_doc.exists:
            session.pop('mentor_email', None)
            return redirect(url_for('mentor_register'))
        
        # Get pending and upcoming sessions
        now = datetime.now().isoformat()
        pending_sessions = db.collection('sessions')\
                           .where('mentor_email', '==', session['mentor_email'])\
                           .where('status', '==', 'pending')\
                           .order_by('created_at')\
                           .stream()
        
        upcoming_sessions = db.collection('sessions')\
                            .where('mentor_email', '==', session['mentor_email'])\
                            .where('status', 'in', ['accepted', 'completed'])\
                            .where('date', '>=', now)\
                            .order_by('date')\
                            .limit(5)\
                            .stream()
        
        return render_template('mentor_dashboard.html', 
                            mentor=mentor_doc.to_dict(),
                            pending_sessions=[s.to_dict() for s in pending_sessions],
                            upcoming_sessions=[s.to_dict() for s in upcoming_sessions])
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return redirect(url_for('mentor_register'))
@app.route('/accept-session/<session_id>')
@mentor_required
def accept_session(session_id):
    try:
        session_ref = db.collection('sessions').document(session_id)
        session_data = session_ref.get().to_dict()
        
        # Verify mentor owns this session
        if session_data['mentor_email'] != session['mentor_email']:
            flash("Unauthorized action", "error")
            return redirect(url_for('mentor_dashboard'))
        
        # Create Stripe payment link
        mentor = db.collection('mentors').document(session['mentor_email']).get().to_dict()
        amount = int(mentor['hourly_charge'] * (session_data['duration'] / 60) * 100)
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': f"Session with {mentor['name']}"},
                    'unit_amount': amount,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('payment_success', session_id=session_id, _external=True),
            cancel_url=url_for('payment_cancel', _external=True),
        )
        
        # Update session status
        session_ref.update({
            'status': 'accepted',
            'payment_link': checkout_session.url,
            'payment_id': checkout_session.id
        })
        
        # Notify student
        student = db.collection('students').document(session_data['student_email']).get().to_dict()
        send_email(
            student['email'],
            "Session Accepted!",
            f"Your mentor has accepted the session. Pay now: {checkout_session.url}"
        )
        
        return redirect(checkout_session.url)
    except Exception as e:
        flash(f"Error: {str(e)}", "error")
 
        return redirect(url_for('mentor_dashboard'))
# ... [all your existing imports and configurations stay at the top] ...

# ... [keep all existing routes before this point] ...

# ===== ADD THE NEW ROUTE HERE =====
# AFTER your existing mentor routes but BEFORE these final lines:

# --- Mentor Booking System ---
@app.route('/request-session', methods=['POST'])
def request_session():
    # ... [your existing request-session route] ...

# ADD THE ACCEPT-SESSION ROUTE RIGHT HERE
@app.route('/accept-session/<session_id>')
@mentor_required
def accept_session(session_id):
    try:
        session_ref = db.collection('sessions').document(session_id)
        session_data = session_ref.get().to_dict()
        
        # Verify mentor owns this session
        if session_data['mentor_email'] != session['mentor_email']:
            flash("Unauthorized action", "error")
            return redirect(url_for('mentor_dashboard'))
        
        # Create Stripe payment link
        mentor = db.collection('mentors').document(session['mentor_email']).get().to_dict()
        amount = int(mentor['hourly_charge'] * (session_data['duration'] / 60) * 100
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': f"Session with {mentor['name']}"},
                    'unit_amount': amount,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('payment_success', session_id=session_id, _external=True),
            cancel_url=url_for('payment_cancel', _external=True),
        )
        
        # Update session status
        session_ref.update({
            'status': 'accepted',
            'payment_link': checkout_session.url,
            'payment_id': checkout_session.id
        })
        
        # Notify student
        student = db.collection('students').document(session_data['student_email']).get().to_dict()
        send_email(
            student['email'],
            "Session Accepted!",
            f"Your mentor has accepted the session. Pay now: {checkout_session.url}"
        )
        
        return redirect(checkout_session.url)
    except Exception as e:
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('mentor_dashboard'))

# --- Payment Handlers (add these next) ---
@app.route('/payment-success/<session_id>')
def payment_success(session_id):
    # ... [payment success handler] ...

@app.route('/payment-cancel')
def payment_cancel():
    # ... [payment cancel handler] ...

# ==== KEEP THIS AT THE VERY BOTTOM ====
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)        
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
