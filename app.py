import os
import logging
from datetime import datetime
from functools import wraps
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, url_for, flash, redirect, request, jsonify, send_from_directory, abort, session
from flask_login import login_user, current_user, logout_user, login_required, LoginManager, UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.orm import joinedload
from sqlalchemy import and_  # Import de and_
import json
from datetime import timedelta
from urllib.parse import urlparse

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

logger.info('Application démarrée')

import sys
from extensions import db, migrate, bcrypt, csrf

# Import des formulaires
from forms import (LoginForm, RegistrationForm, ClassForm, CourseForm, 
                  ExerciseForm, GradeForm, TextHoleForm, QuestionForm, ChoiceForm)

# Configuration de l'application
app = Flask(__name__)
app.config.from_object('config')
app.config['SECRET_KEY'] = 'votre_cle_secrete_ici'  # Remplacer par une vraie clé secrète
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)  # Sessions durent 7 jours
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=7)    # Cookie "remember me" dure 7 jours
app.config['REMEMBER_COOKIE_SECURE'] = False  # Mettre à True en production
app.config['REMEMBER_COOKIE_HTTPONLY'] = True

# Initialisation des extensions
db.init_app(app)
migrate.init_app(app, db)
bcrypt.init_app(app)
csrf.init_app(app)

# Initialisation de Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.session_protection = "strong"

@login_manager.user_loader
def load_user(user_id):
    print(f"Loading user {user_id}")  # Debug print
    return User.query.get(int(user_id))

# Import des modèles et des formulaires après l'initialisation de db
from models import User, Class, Course, Exercise, ExerciseSubmission, CourseFile, Question, Choice, TextHole, ClassEnrollment, ClassExercise
from logs import logger, log_database_error, log_form_data, log_model_creation, log_request_info

# Configuration du dossier d'upload
UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configuration des dossiers statiques
app.static_folder = 'static'
app.static_url_path = '/static'

# Configuration des extensions de fichiers autorisées
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Décorateur pour restreindre l'accès aux enseignants
def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_teacher:
            flash('Accès non autorisé. Vous devez être un enseignant.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Routes de base
@app.route('/')
@app.route('/index')
def index():
    if current_user.is_authenticated:
        if current_user.is_teacher:
            return redirect(url_for('teacher_dashboard'))
        return redirect(url_for('student_dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        print(f"User {current_user.id} already authenticated")  # Debug print
        if current_user.is_teacher:
            return redirect(url_for('teacher_dashboard'))
        return redirect(url_for('student_dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            print(f"Login successful for user {user.id}")  # Debug print
            # Définir la session comme permanente si "remember me" est coché
            if form.remember.data:
                session.permanent = True
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            if not next_page or urlparse(next_page).netloc != '':
                if user.is_teacher:
                    next_page = url_for('teacher_dashboard')
                else:
                    next_page = url_for('student_dashboard')
            return redirect(next_page)
        else:
            print(f"Login failed for email {form.email.data}")  # Debug print
            flash('Email ou mot de passe incorrect.', 'danger')
    
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        logger.debug(f"Tentative d'inscription avec : username={form.username.data}, email={form.email.data}, user_type={form.user_type.data}")
        try:
            user = User(
                username=form.username.data,
                email=form.email.data,
                role=form.user_type.data
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            logger.info(f"Nouvel utilisateur créé : {user.username} (ID: {user.id})")
            
            flash('Inscription réussie! Vous pouvez maintenant vous connecter.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            logger.error(f"Erreur lors de l'inscription : {str(e)}")
            db.session.rollback()
            flash('Une erreur est survenue lors de l\'inscription.', 'danger')
    else:
        if form.errors:
            logger.debug(f"Erreurs de validation du formulaire : {form.errors}")
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'Erreur dans le champ {field}: {error}', 'danger')
    
    return render_template('register.html', title='Inscription', form=form)

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    logout_user()
    flash('Vous avez été déconnecté avec succès.', 'info')
    return redirect(url_for('login'))

@app.route('/teacher-dashboard')
@login_required
def teacher_dashboard():
    if not current_user.is_teacher:
        flash('Accès non autorisé. Cette page est réservée aux enseignants.', 'danger')
        return redirect(url_for('index'))
    
    # Récupérer les statistiques de l'enseignant
    stats = current_user.get_teacher_stats()
    logger.debug(f"Statistiques de l'enseignant : {stats}")
    
    # Récupérer les classes de l'enseignant
    classes = Class.query.filter_by(teacher_id=current_user.id).all()
    
    # Récupérer les soumissions récentes avec scores
    recent_submissions = ExerciseSubmission.query\
        .join(Exercise)\
        .join(Course)\
        .join(Class)\
        .filter(Class.teacher_id == current_user.id)\
        .order_by(ExerciseSubmission.submitted_at.desc())\
        .limit(10)\
        .all()
    
    # Récupérer les soumissions en attente de notation
    pending_submissions = ExerciseSubmission.query\
        .join(Exercise)\
        .join(Course)\
        .join(Class)\
        .filter(Class.teacher_id == current_user.id)\
        .filter(ExerciseSubmission.score.is_(None))\
        .order_by(ExerciseSubmission.submitted_at.desc())\
        .limit(5)\
        .all()
    
    return render_template('teacher_dashboard.html', 
                         title='Tableau de Bord',
                         stats=stats,
                         classes=classes,
                         recent_submissions=recent_submissions,
                         pending_submissions=pending_submissions)

@app.route('/student-dashboard')
@login_required
def student_dashboard():
    if current_user.is_teacher:
        return redirect(url_for('teacher_dashboard'))
    
    # Récupérer les inscriptions de l'étudiant
    enrollments = ClassEnrollment.query.filter_by(student_id=current_user.id).all()
    student_classes = [enrollment.enrolled_class for enrollment in enrollments]
    
    # Récupérer les soumissions d'exercices de l'étudiant
    submissions = ExerciseSubmission.query.filter_by(student_id=current_user.id).order_by(ExerciseSubmission.submitted_at.desc()).limit(5).all()
    
    return render_template('student_dashboard.html', classes=student_classes, submissions=submissions)

@app.route('/classes/join', methods=['POST'])
@login_required
def join_class():
    if current_user.is_teacher:
        flash('Seuls les étudiants peuvent rejoindre une classe.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    class_code = request.form.get('class_code')
    if not class_code:
        flash('Le code de la classe est requis.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    # Trouver la classe avec ce code
    class_obj = Class.query.filter_by(invite_code=class_code).first()
    if not class_obj:
        flash('Code de classe invalide.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    # Vérifier si l'étudiant est déjà inscrit
    existing_enrollment = ClassEnrollment.query.filter_by(
        student_id=current_user.id,
        class_id=class_obj.id
    ).first()
    
    if existing_enrollment:
        flash('Vous êtes déjà inscrit dans cette classe.', 'info')
        return redirect(url_for('view_class', class_id=class_obj.id))
    
    try:
        # Créer une nouvelle inscription
        enrollment = ClassEnrollment(
            student_id=current_user.id,
            class_id=class_obj.id
        )
        db.session.add(enrollment)
        db.session.commit()
        
        flash('Vous avez rejoint la classe avec succès!', 'success')
        return redirect(url_for('view_class', class_id=class_obj.id))
        
    except Exception as e:
        db.session.rollback()
        print(f"Error joining class: {str(e)}")
        flash('Une erreur est survenue lors de l\'inscription à la classe.', 'danger')
        return redirect(url_for('student_dashboard'))

@app.route('/classes/create', methods=['GET', 'POST'])
@login_required
def create_class():
    form = ClassForm()
    if request.method == 'POST':
        log_request_info(request)
        try:
            if form.validate_on_submit():
                new_class = Class(
                    name=form.name.data,
                    description=form.description.data,
                    teacher_id=current_user.id
                )
                log_model_creation('Class', {
                    'name': new_class.name,
                    'teacher_id': new_class.teacher_id
                })
                
                db.session.add(new_class)
                db.session.commit()
                
                logger.info(f"Class created successfully with ID: {new_class.id}")
                flash('Classe créée avec succès!', 'success')
                return redirect(url_for('view_class', class_id=new_class.id))
            else:
                logger.warning(f"Form validation failed: {form.errors}")
                flash('Erreur dans le formulaire. Veuillez vérifier les champs.', 'danger')
        except Exception as e:
            log_database_error(e, "create_class route")
            db.session.rollback()
            flash('Une erreur est survenue lors de la création de la classe.', 'danger')
    
    return render_template('create_class.html', form=form)

@app.route('/course/create/<int:class_id>', methods=['GET', 'POST'])
@login_required
@teacher_required
def create_course(class_id):
    class_ = Class.query.get_or_404(class_id)
    
    if class_.teacher_id != current_user.id:
        flash('Vous n\'avez pas l\'autorisation de créer un cours dans cette classe.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    form = CourseForm()
    if form.validate_on_submit():
        try:
            course = Course(
                title=form.title.data,
                description=form.description.data,
                content=form.content.data,
                class_id=class_id
            )
            db.session.add(course)
            db.session.commit()

            # Gestion des fichiers joints
            if form.files.data:
                course_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'course_{course.id}')
                os.makedirs(course_folder, exist_ok=True)
                
                for file in form.files.data:
                    if file and allowed_file(file.filename):
                        try:
                            filename = secure_filename(file.filename)
                            file_path = os.path.join(course_folder, filename)
                            file.save(file_path)
                            
                            course_file = CourseFile(
                                filename=filename,
                                file_path=file_path,
                                course_id=course.id
                            )
                            db.session.add(course_file)
                        except Exception as e:
                            logger.error(f"Erreur lors de l'upload du fichier {file.filename}: {str(e)}")
                            flash(f'Erreur lors de l\'upload du fichier {file.filename}', 'warning')
                            continue
                    else:
                        flash(f'Le fichier {file.filename} n\'est pas autorisé', 'warning')
                
                try:
                    db.session.commit()
                except Exception as e:
                    logger.error(f"Erreur lors de l'enregistrement des fichiers: {str(e)}")
                    db.session.rollback()
                    flash('Erreur lors de l\'enregistrement des fichiers', 'warning')

            flash(f'Le cours "{form.title.data}" a été créé avec succès.', 'success')
            return redirect(url_for('view_class', class_id=class_id))
            
        except Exception as e:
            logger.error(f"Erreur lors de la création du cours: {str(e)}")
            db.session.rollback()
            flash('Une erreur est survenue lors de la création du cours.', 'danger')

    return render_template('create_course.html', form=form, class_=class_)

@app.route('/create-exercise', methods=['GET', 'POST'])
@login_required
@teacher_required
def create_exercise():
    form = ExerciseForm()
    
    # Récupérer le class_id de l'URL
    class_id = request.args.get('class_id', type=int)
    logger.info(f"Class ID from URL: {class_id}")
    
    # Récupérer toutes les classes de l'enseignant avec leurs cours
    if class_id:
        # Si class_id est fourni, ne récupérer que cette classe
        teacher_classes = Class.query.filter_by(id=class_id, teacher_id=current_user.id).all()
        if not teacher_classes:
            flash('Classe non trouvée ou non autorisée.', 'danger')
            return redirect(url_for('teacher_dashboard'))
    else:
        # Sinon, récupérer toutes les classes de l'enseignant
        teacher_classes = Class.query.filter_by(teacher_id=current_user.id).all()
    
    # Log pour le débogage
    logger.info(f"Classes de l'enseignant: {[c.name for c in teacher_classes]}")
    for class_ in teacher_classes:
        logger.info(f"Cours dans {class_.name}: {[c.title for c in class_.courses]}")
    
    if request.method == 'POST':
        logger.info("=== Début de la création d'exercice ===")
        logger.info(f"Données du formulaire: {request.form}")
        
        try:
            # Récupérer le course_id du formulaire
            course_id = request.form.get('course_id')
            logger.info(f"Course ID reçu: {course_id}")
            
            if not course_id:
                logger.warning("Aucun course_id fourni")
                flash('Veuillez sélectionner un cours.', 'danger')
                return render_template('create_exercise.html', form=form, teacher_classes=teacher_classes)

            # Vérifier que le cours existe et appartient à l'enseignant
            course = Course.query.get(course_id)
            if not course:
                logger.warning(f"Cours {course_id} non trouvé")
                flash('Cours invalide.', 'danger')
                return render_template('create_exercise.html', form=form, teacher_classes=teacher_classes)
                
            if course.class_.teacher_id != current_user.id:
                logger.warning(f"Le cours {course_id} n'appartient pas à l'enseignant {current_user.id}")
                flash('Cours invalide.', 'danger')
                return render_template('create_exercise.html', form=form, teacher_classes=teacher_classes)

            logger.info(f"Cours valide: {course.title}")

            # Créer l'exercice
            exercise = Exercise(
                title=request.form.get('title'),
                description=request.form.get('description'),
                subject=request.form.get('subject'),
                level=request.form.get('level'),
                difficulty=request.form.get('difficulty'),
                points=request.form.get('points'),
                exercise_type=request.form.get('exercise_type'),
                course_id=course_id,
                created_by=current_user.id
            )
            
            logger.info(f"Exercice créé: {exercise.title} (type: {exercise.exercise_type})")
            
            # Ajouter les trous si c'est un exercice à trous
            if exercise.exercise_type == 'holes':
                holes_data = request.form.get('holes_data')
                logger.info(f"Données des trous reçues: {holes_data}")
                
                if not holes_data:
                    logger.warning("Aucune donnée de trous reçue pour un exercice de type 'holes'")
                    raise ValueError("Données des trous manquantes")
                
                try:
                    holes = json.loads(holes_data)
                    logger.info(f"Nombre de trous: {len(holes)}")
                    
                    if not holes:
                        raise ValueError("Au moins un trou est requis")
                    
                    for i, hole_data in enumerate(holes):
                        # Valider les données du trou
                        if not hole_data.get('correct_answer'):
                            raise ValueError(f"Réponse manquante pour le trou #{i+1}")
                        
                        hole = TextHole(
                            text_before=hole_data.get('text_before', ''),
                            correct_answer=hole_data['correct_answer'],
                            text_after=hole_data.get('text_after', '')
                        )
                        logger.info(f"Trou #{i+1} créé: {hole.correct_answer}")
                        exercise.text_holes.append(hole)
                        
                except json.JSONDecodeError as e:
                    logger.error(f"Erreur de décodage JSON des trous: {e}")
                    raise ValueError("Format des données des trous invalide")

            db.session.add(exercise)
            db.session.commit()
            logger.info(f"Exercice {exercise.id} enregistré avec succès")
            
            # Rediriger vers le cours si class_id est fourni
            if class_id:
                flash('Exercice créé avec succès!', 'success')
                return redirect(url_for('view_class', class_id=class_id))
            else:
                flash('Exercice créé avec succès!', 'success')
                return redirect(url_for('exercise_library'))
            
        except ValueError as ve:
            db.session.rollback()
            logger.error(f"Erreur de validation: {str(ve)}")
            flash(str(ve), 'danger')
            return render_template('create_exercise.html', form=form, teacher_classes=teacher_classes)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erreur inattendue lors de la création de l'exercice: {str(e)}")
            flash('Une erreur est survenue lors de la création de l\'exercice.', 'danger')
            return render_template('create_exercise.html', form=form, teacher_classes=teacher_classes)
        finally:
            logger.info("=== Fin de la création d'exercice ===")

    return render_template('create_exercise.html', form=form, teacher_classes=teacher_classes)

@app.route('/exercise/<int:exercise_id>/edit_holes', methods=['GET', 'POST'])
@login_required
@teacher_required
def edit_holes(exercise_id):
    exercise = Exercise.query.get_or_404(exercise_id)
    if not current_user.is_teacher or current_user.id != exercise.course.class_.teacher_id:
        flash('Accès non autorisé.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Supprimer les anciens trous
        for hole in exercise.text_holes:
            db.session.delete(hole)
        db.session.commit()

        # Créer les nouveaux trous
        texts_before = request.form.getlist('text_before[]')
        answers = request.form.getlist('answer[]')
        texts_after = request.form.getlist('text_after[]')

        for i, (text_before, answer, text_after) in enumerate(zip(texts_before, answers, texts_after), 1):
            if text_before.strip() and answer.strip():
                hole = TextHole(
                    text_before=text_before,
                    correct_answer=answer,
                    text_after=text_after,
                    exercise=exercise
                )
                db.session.add(hole)

        db.session.commit()
        log_request_info(request)
        log_form_data(request.form.to_dict(), 'edit_holes')
        logger.info(f"Exercise holes updated successfully for exercise ID: {exercise_id}")
        flash('Exercice à trous mis à jour avec succès!', 'success')
        return redirect(url_for('view_exercise', exercise_id=exercise_id))

    return render_template('edit_holes.html', exercise=exercise)

@app.route('/exercise/<int:exercise_id>/delete', methods=['POST'])
@login_required
@teacher_required
def delete_exercise(exercise_id):
    try:
        logger.info(f"Tentative de suppression de l'exercice {exercise_id}")
        exercise = Exercise.query.get_or_404(exercise_id)
        
        # Vérifier que l'utilisateur est bien le professeur de la classe
        if exercise.course.class_.teacher_id != current_user.id:
            logger.warning(f"Tentative non autorisée de suppression de l'exercice {exercise_id} par l'utilisateur {current_user.id}")
            flash('Vous n\'avez pas l\'autorisation de supprimer cet exercice.', 'danger')
            return redirect(url_for('view_class', class_id=exercise.course.class_.id))
        
        # Récupérer l'ID de la classe avant de supprimer l'exercice
        class_id = exercise.course.class_id
        
        # Supprimer d'abord les questions et les choix si c'est un QCM
        if exercise.exercise_type == 'qcm':
            logger.info(f"Suppression des questions et choix du QCM {exercise_id}")
            for question in exercise.questions:
                for choice in question.choices:
                    db.session.delete(choice)
                db.session.delete(question)
        
        # Supprimer les trous si c'est un exercice à trous
        elif exercise.exercise_type == 'text_holes':
            logger.info(f"Suppression des trous de l'exercice {exercise_id}")
            for hole in exercise.text_holes:
                db.session.delete(hole)
        
        # Supprimer les soumissions liées à cet exercice
        logger.info(f"Suppression des soumissions de l'exercice {exercise_id}")
        ExerciseSubmission.query.filter_by(exercise_id=exercise_id).delete()
        
        # Supprimer l'exercice
        logger.info(f"Suppression de l'exercice {exercise_id}")
        db.session.delete(exercise)
        db.session.commit()
        
        flash('Exercice supprimé avec succès.', 'success')
        return redirect(url_for('view_class', class_id=class_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la suppression de l'exercice {exercise_id}: {str(e)}")
        logger.exception("Traceback complet:")
        flash('Une erreur est survenue lors de la suppression de l\'exercice.', 'danger')
        return redirect(url_for('view_class', class_id=class_id))

@app.route('/exercise/<int:exercise_id>/edit/qcm', methods=['GET', 'POST'])
@login_required
@teacher_required
def edit_qcm(exercise_id):
    exercise = Exercise.query.get_or_404(exercise_id)
    if not current_user.is_teacher:
        flash('Seuls les enseignants peuvent modifier les exercices.', 'danger')
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        try:
            # Supprimer toutes les questions et choix existants
            for question in exercise.questions:
                db.session.delete(question)
            db.session.commit()
            
            # Récupérer tous les champs du formulaire
            form_data = request.form
            
            # Créer un dictionnaire pour stocker les questions et leurs choix
            questions_data = {}
            
            # Parcourir tous les champs du formulaire
            for key, value in form_data.items():
                if key.startswith('question_text_'):
                    question_index = int(key.split('_')[-1])
                    if value.strip():  # Ignorer les questions vides
                        questions_data[question_index] = {
                            'text': value.strip(),
                            'choices': []
                        }
                        
                elif key.startswith('choice_text_'):
                    # Extraire les IDs de la question et du choix
                    question_id, choice_id = key.split('_')[-2:]
                    is_correct = form_data.get(f'is_correct_{question_id}_{choice_id}') == 'on'
                    
                    if value.strip():  # Ignorer les choix vides
                        if question_id not in questions_data:
                            continue
                        
                        questions_data[question_id]['choices'].append({
                            'text': value.strip(),
                            'is_correct': is_correct
                        })
            
            # Créer les nouvelles questions et choix
            for question_index, question_data in questions_data.items():
                question = Question(
                    text=question_data['text'],
                    exercise_id=exercise.id,
                    position=question_index
                )
                db.session.add(question)
                db.session.flush()  # Pour obtenir l'ID de la question
                
                for choice_index, choice_data in enumerate(question_data['choices']):
                    choice = Choice(
                        text=choice_data['text'],
                        is_correct=choice_data['is_correct'],
                        question_id=question.id,
                        position=choice_index
                    )
                    db.session.add(choice)
            
            db.session.commit()
            flash('QCM mis à jour avec succès!', 'success')
            return redirect(url_for('view_exercise', exercise_id=exercise.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour du QCM: {str(e)}', 'danger')
            logger.error(f'Erreur lors de la mise à jour du QCM: {str(e)}')
    
    return render_template('edit_qcm.html', exercise=exercise)

@app.route('/exercise_library')
@login_required
def exercise_library():
    exercises = Exercise.query.all()  # Récupérer tous les exercices pour l'instant
    teacher_classes = []
    if current_user.is_teacher:
        teacher_classes = Class.query.filter_by(teacher_id=current_user.id).all()
    return render_template('exercise_library.html', exercises=exercises, teacher_classes=teacher_classes)

@app.route('/api/filter_exercises')
@login_required
def filter_exercises():
    subject = request.args.get('subject')
    level = request.args.get('level')
    class_id = request.args.get('class_id')
    exercise_type = request.args.get('type')
    
    logger.info(f"Filtrage des exercices - Paramètres reçus: subject={subject}, level={level}, class_id={class_id}, type={exercise_type}")
    
    query = Exercise.query
    
    if subject:
        logger.debug(f"Filtrage par matière: {subject}")
        query = query.filter_by(subject=subject)
    if level:
        logger.debug(f"Filtrage par niveau: {level}")
        query = query.filter_by(level=level)
    if class_id:
        logger.debug(f"Filtrage par classe: {class_id}")
        query = query.join(ClassExercise).filter(ClassExercise.class_id == class_id)
    if exercise_type:
        logger.debug(f"Filtrage par type: {exercise_type}")
        query = query.filter_by(exercise_type=exercise_type)
    
    exercises = query.order_by(Exercise.created_at.desc()).all()
    logger.info(f"Nombre d'exercices trouvés: {len(exercises)}")
    
    exercise_list = []
    for ex in exercises:
        exercise_data = {
            'id': ex.id,
            'title': ex.title,
            'description': ex.description,
            'subject': ex.subject,
            'level': ex.level,
            'type': ex.exercise_type,
            'created_at': ex.created_at.strftime('%d/%m/%Y') if ex.created_at else None
        }
        exercise_list.append(exercise_data)
        logger.debug(f"Exercice ajouté à la liste: ID={ex.id}, Titre={ex.title}")
    
    return jsonify(exercise_list)

@app.route('/exercise/<int:exercise_id>/add_to_class', methods=['POST'])
@login_required
@teacher_required
def add_exercise_to_class(exercise_id):
    if not current_user.is_teacher:
        return jsonify({'error': 'Accès non autorisé'}), 403
        
    class_id = request.args.get('class_id')
    if not class_id:
        return jsonify({'error': 'ID de classe manquant'}), 400
        
    try:
        # Vérifier que l'exercice existe
        exercise = Exercise.query.get_or_404(exercise_id)
        
        # Vérifier que la classe existe et appartient au professeur
        class_obj = Class.query.filter_by(id=class_id, teacher_id=current_user.id).first()
        if not class_obj:
            return jsonify({'error': 'Classe non trouvée ou non autorisée'}), 404
            
        # Vérifier si l'exercice n'est pas déjà dans la classe
        if exercise in class_obj.exercises:
            return jsonify({'message': 'L\'exercice est déjà dans cette classe'})
            
        # Ajouter l'exercice à la classe
        class_obj.exercises.append(exercise)
        db.session.commit()
        
        return jsonify({
            'message': f'Exercice ajouté à la classe {class_obj.name}',
            'exercise_id': exercise_id,
            'class_id': class_id
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/course/<int:course_id>/edit', methods=['GET', 'POST'])
@login_required
@teacher_required
def edit_course(course_id):
    course = Course.query.get_or_404(course_id)
    class_ = Class.query.get_or_404(course.class_id)
    
    # Vérifier que l'utilisateur est le professeur de cette classe
    if current_user.id != class_.teacher_id:
        flash('Vous n\'avez pas l\'autorisation de modifier ce cours.', 'danger')
        return redirect(url_for('view_class', class_id=class_.id))
    
    if request.method == 'POST':
        course.title = request.form['title']
        course.description = request.form['description']
        course.content = request.form['content']
        
        # Gérer les fichiers uploadés
        if 'files' in request.files:
            files = request.files.getlist('files')
            for file in files:
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    course_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'course_{course_id}')
                    os.makedirs(course_folder, exist_ok=True)
                    
                    file_path = os.path.join(course_folder, filename)
                    file.save(file_path)
                    
                    course_file = CourseFile(
                        filename=filename,
                        file_path=file_path,
                        course_id=course.id
                    )
                    db.session.add(course_file)
            
            db.session.commit()

        log_request_info(request)
        log_form_data(request.form.to_dict(), 'edit_course')
        logger.info(f"Course updated successfully with ID: {course_id}")
        flash('Le cours a été mis à jour avec succès.', 'success')
        return redirect(url_for('view_course', course_id=course.id))
    
    return render_template('create_course.html', course=course, class_=class_, edit_mode=True)

@app.route('/course/file/<int:file_id>')
@login_required
def download_course_file(file_id):
    course_file = CourseFile.query.get_or_404(file_id)
    course = course_file.course
    class_ = course.class_

    # Vérifier que l'utilisateur a accès à ce fichier
    if current_user.id != class_.teacher_id and current_user not in [enrollment.student for enrollment in class_.enrolled_students]:
        flash('Vous n\'avez pas accès à ce fichier.', 'danger')
        return redirect(url_for('index'))

    try:
        return send_file(
            course_file.file_path,
            as_attachment=True,
            download_name=course_file.filename
        )
    except Exception as e:
        log_database_error(e, "download_course_file route")
        flash('Erreur lors du téléchargement du fichier.', 'danger')
        return redirect(url_for('view_course', course_id=course.id))

@app.route('/course/file/<int:file_id>/view')
@login_required
def view_course_file(file_id):
    file = CourseFile.query.get_or_404(file_id)
    if current_user.id != file.course.teacher_id and not current_user in file.course.students:
        flash('Accès non autorisé.', 'danger')
        return redirect(url_for('index'))
    
    return send_from_directory(os.path.dirname(file.file_path), os.path.basename(file.file_path))

@app.route('/course/file/<int:file_id>', methods=['DELETE'])
@login_required
@teacher_required
def delete_course_file(file_id):
    file = CourseFile.query.get_or_404(file_id)
    if current_user.id != file.course.teacher_id:
        return jsonify({'error': 'Accès non autorisé'}), 403

    try:
        # Supprimer le fichier physique
        if os.path.exists(file.file_path):
            os.remove(file.file_path)
        
        # Supprimer l'entrée de la base de données
        db.session.delete(file)
        db.session.commit()
        
        log_request_info(request)
        logger.info(f"Course file deleted successfully with ID: {file_id}")
        return jsonify({'message': 'Fichier supprimé avec succès'}), 200
    except Exception as e:
        log_database_error(e, "delete_course_file route")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/courses/<int:course_id>')
@login_required
def view_course(course_id):
    course = Course.query.get_or_404(course_id)
    class_obj = Class.query.get_or_404(course.class_id)
    
    # Vérifier si l'utilisateur a accès au cours
    if not current_user.is_teacher:
        # Pour les étudiants, vérifier s'ils sont dans la liste des étudiants de la classe
        if current_user not in class_obj.students:
            flash('Vous n\'avez pas accès à ce cours.', 'danger')
            return redirect(url_for('student_dashboard'))
    elif class_obj.teacher_id != current_user.id:
        flash('Vous n\'avez pas accès à ce cours.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    # Récupérer les exercices de ce cours
    exercises = Exercise.query.filter_by(course_id=course_id).order_by(Exercise.title).all()
    
    # Récupérer les fichiers attachés au cours
    course_files = CourseFile.query.filter_by(course_id=course_id).all()
    
    return render_template('view_course.html', 
                         course=course,
                         exercises=exercises,
                         course_files=course_files)

@app.route('/courses/<int:course_id>/delete', methods=['POST'])
@login_required
@teacher_required
def delete_course(course_id):
    try:
        logger.info(f"Tentative de suppression du cours {course_id}")
        course = Course.query.get_or_404(course_id)
        
        # Vérifier que l'utilisateur est bien le professeur de la classe
        if course.class_.teacher_id != current_user.id:
            logger.warning(f"Tentative non autorisée de suppression du cours {course_id} par l'utilisateur {current_user.id}")
            flash('Vous n\'êtes pas autorisé à supprimer ce cours.', 'danger')
            return redirect(url_for('view_class', class_id=course.class_id))
        
        # Récupérer l'ID de la classe avant de supprimer le cours
        class_id = course.class_id
        
        # Supprimer d'abord tous les exercices liés au cours
        for exercise in course.exercises:
            # Supprimer les questions et les choix si c'est un QCM
            if exercise.exercise_type == 'qcm':
                logger.info(f"Suppression des questions et choix du QCM {exercise.id}")
                for question in exercise.questions:
                    for choice in question.choices:
                        db.session.delete(choice)
                    db.session.delete(question)
            
            # Supprimer les trous si c'est un exercice à trous
            elif exercise.exercise_type == 'text_holes':
                logger.info(f"Suppression des trous de l'exercice {exercise.id}")
                for hole in exercise.text_holes:
                    db.session.delete(hole)
            
            # Supprimer les soumissions liées à cet exercice
            logger.info(f"Suppression des soumissions de l'exercice {exercise.id}")
            ExerciseSubmission.query.filter_by(exercise_id=exercise.id).delete()
            
            # Supprimer l'exercice
            logger.info(f"Suppression de l'exercice {exercise.id}")
            db.session.delete(exercise)
        
        # Supprimer les fichiers du cours
        for file in course.files:
            logger.info(f"Suppression du fichier {file.filename}")
            db.session.delete(file)
            # Supprimer le fichier physique
            if os.path.exists(file.file_path):
                os.remove(file.file_path)
        
        # Supprimer le cours
        logger.info(f"Suppression du cours {course_id}")
        db.session.delete(course)
        db.session.commit()
        
        flash('Cours supprimé avec succès.', 'success')
        return redirect(url_for('view_class', class_id=class_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la suppression du cours {course_id}: {str(e)}")
        logger.exception("Traceback complet:")
        flash('Une erreur est survenue lors de la suppression du cours.', 'danger')
        return redirect(url_for('view_class', class_id=class_id))

@app.route('/exercises/<int:exercise_id>')
@login_required
def view_exercise(exercise_id):
    logger.info(f"Tentative d'accès à l'exercice {exercise_id} par l'utilisateur {current_user.id}")
    
    try:
        exercise = Exercise.query.options(
            joinedload(Exercise.questions).joinedload(Question.choices),
            joinedload(Exercise.text_holes),
            joinedload(Exercise.submissions).joinedload(ExerciseSubmission.submitting_student)
        ).get_or_404(exercise_id)
        logger.debug(f"Exercice trouvé: ID={exercise.id}, Titre={exercise.title}, Type={exercise.exercise_type}")
        
        # Vérifier si l'utilisateur est inscrit au cours
        is_enrolled = False
        if not current_user.is_teacher:
            enrollment = ClassEnrollment.query.filter_by(
                student_id=current_user.id,
                class_id=exercise.course.class_.id
            ).first()
            is_enrolled = enrollment is not None
            logger.debug(f"Statut d'inscription de l'étudiant: {is_enrolled}")
        
        # Récupérer la dernière soumission de l'utilisateur
        user_submission = None
        if not current_user.is_teacher:
            user_submission = ExerciseSubmission.query.filter_by(
                student_id=current_user.id,
                exercise_id=exercise_id
            ).order_by(ExerciseSubmission.submitted_at.desc()).first()
            
            if user_submission:
                logger.debug(f"Dernière soumission trouvée: ID={user_submission.id}, Score={user_submission.score}")
            else:
                logger.debug("Aucune soumission trouvée pour cet utilisateur")
        
        return render_template('view_exercise.html',
                          exercise=exercise,
                          is_enrolled=is_enrolled,
                          user_submission=user_submission)
                          
    except Exception as e:
        logger.error(f"Erreur lors de l'accès à l'exercice {exercise_id}: {str(e)}")
        flash("Une erreur s'est produite lors de l'accès à l'exercice.", 'danger')
        return redirect(url_for('exercise_library'))

@app.route('/submit_exercise/<int:exercise_id>', methods=['POST'])
def submit_exercise(exercise_id):
    try:
        logger.info(f"Tentative de soumission pour l'exercice {exercise_id}")
        exercise = Exercise.query.get_or_404(exercise_id)
        
        # Vérifier si l'étudiant est inscrit au cours
        enrollment = ClassEnrollment.query.filter_by(
            student_id=current_user.id,
            class_id=exercise.course.class_.id
        ).first()
        
        if not enrollment:
            logger.warning(f"Étudiant {current_user.id} non inscrit au cours pour l'exercice {exercise_id}")
            flash("Vous n'êtes pas inscrit à ce cours.", 'danger')
            return redirect(url_for('view_exercise', exercise_id=exercise_id))

        # Récupérer les réponses
        answers = {}
        score = 0
        total_holes = len(exercise.text_holes)
        correct_answers = 0

        logger.info("Traitement des réponses...")
        for hole in exercise.text_holes:
            answer_key = f'hole_{hole.id}'
            student_answer = request.form.get(answer_key, '').strip().lower()
            correct_answer = hole.correct_answer.strip().lower()
            logger.debug(f"Trou {hole.id}: réponse = {student_answer}, réponse correcte = {correct_answer}")
            
            if student_answer == correct_answer:
                correct_answers += 1
            answers[hole.id] = student_answer

        if total_holes > 0:
            score = (correct_answers / total_holes) * 100
            logger.info(f"Score calculé: {score}%")

        # Créer une nouvelle soumission avec le score calculé
        submission = ExerciseSubmission(
            student_id=current_user.id,
            exercise_id=exercise_id,
            submitted_at=datetime.utcnow(),
            score=score,
            answers=str(answers)
        )
        
        db.session.add(submission)
        db.session.commit()
        logger.info(f"Soumission exercice sauvegardée - Étudiant: {current_user.id}, Exercise: {exercise_id}, Score: {score}")

        flash(f'Exercice soumis avec succès! Score: {score:.1f}%', 'success')
        return redirect(url_for('view_exercise', exercise_id=exercise_id))

    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la soumission de l'exercice: {str(e)}")
        flash('Une erreur est survenue lors de la soumission.', 'danger')
        return redirect(url_for('view_exercise', exercise_id=exercise_id))

@app.route('/exercises/<int:exercise_id>/edit', methods=['GET', 'POST'])
@login_required
@teacher_required
def edit_exercise(exercise_id):
    exercise = Exercise.query.get_or_404(exercise_id)
    course = Course.query.get_or_404(exercise.course_id)
    class_ = Class.query.get_or_404(course.class_id)
    
    # Vérifier que l'utilisateur est le professeur de la classe
    if current_user.id != class_.teacher_id:
        flash('Vous n\'êtes pas autorisé à modifier cet exercice.', 'danger')
        return redirect(url_for('view_exercise', exercise_id=exercise_id))
    
    form = ExerciseForm(obj=exercise)
    
    if form.validate_on_submit():
        try:
            # Mettre à jour les informations de base
            exercise.title = form.title.data
            exercise.description = form.description.data
            exercise.difficulty = form.difficulty.data
            exercise.points = form.points.data
            exercise.subject = form.subject.data
            exercise.level = form.level.data
            
            # Gérer l'upload d'image
            if form.image.data:
                try:
                    image_filename = secure_filename(form.image.data.filename)
                    exercise_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'exercises/{exercise_id}')
                    os.makedirs(exercise_folder, exist_ok=True)
                    
                    image_filepath = os.path.join(exercise_folder, image_filename)
                    form.image.data.save(image_filepath)
                    exercise.image_path = f'uploads/exercises/{exercise_id}/{image_filename}'
                except Exception as e:
                    logger.error(f"Error saving image: {str(e)}")
                    flash('Erreur lors de l\'enregistrement de l\'image', 'danger')
            
            # Supprimer les anciennes questions/choix ou trous
            if exercise.exercise_type == 'qcm':
                for question in exercise.questions:
                    db.session.delete(question)
                
                # Ajouter les nouvelles questions et choix
                for question_data in form.questions.data:
                    if question_data.get('text'):
                        question = Question(
                            text=question_data['text'],
                            exercise_id=exercise.id
                        )
                        db.session.add(question)
                        db.session.flush()  # Pour obtenir l'ID de la question
                        
                        for choice_data in question_data['choices']:
                            if choice_data.get('text'):
                                choice = Choice(
                                    text=choice_data['text'],
                                    is_correct=choice_data.get('is_correct', False),
                                    question_id=question.id
                                )
                                db.session.add(choice)
            
            elif exercise.exercise_type == 'text_holes':
                for hole in exercise.text_holes:
                    db.session.delete(hole)
                
                # Ajouter les nouveaux trous
                for i, hole_data in enumerate(form.text_holes.data):
                    if hole_data.get('text_before') and hole_data.get('correct_answer'):
                        text_hole = TextHole(
                            text_before=hole_data['text_before'],
                            correct_answer=hole_data['correct_answer'],
                            text_after=hole_data.get('text_after', ''),
                            exercise_id=exercise.id
                        )
                        db.session.add(text_hole)
            
            db.session.commit()
            logger.info(f"Exercise updated successfully with ID: {exercise_id}")
            flash('Exercice mis à jour avec succès!', 'success')
            return redirect(url_for('view_exercise', exercise_id=exercise.id))
            
        except Exception as e:
            logger.error(f"Error updating exercise: {str(e)}")
            db.session.rollback()
            flash('Erreur lors de la mise à jour de l\'exercice', 'danger')
    
    if form.errors:
        logger.debug(f"Form validation errors: {form.errors}")
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'Erreur dans le champ {field}: {error}', 'danger')
    
    # Pré-remplir le formulaire avec les données existantes
    if request.method == 'GET':
        form.title.data = exercise.title
        form.description.data = exercise.description
        form.difficulty.data = exercise.difficulty
        form.points.data = exercise.points
        form.subject.data = exercise.subject
        form.level.data = exercise.level
        
        if exercise.exercise_type == 'qcm':
            form.questions.entries = []
            for question in exercise.questions:
                question_form = QuestionForm()
                question_form.text.data = question.text
                
                choices = []
                for choice in question.choices:
                    choice_form = ChoiceForm()
                    choice_form.text.data = choice.text
                    choice_form.is_correct.data = choice.is_correct
                    choices.append(choice_form)
                
                # Ajouter des choix vides si nécessaire
                while len(choices) < 4:
                    choices.append(ChoiceForm())
                
                question_form.choices = choices
                form.questions.append_entry(question_form)
        
        elif exercise.exercise_type == 'text_holes':
            form.text_holes.entries = []
            for hole in exercise.text_holes:
                hole_form = TextHoleForm()
                hole_form.text_before.data = hole.text_before
                hole_form.correct_answer.data = hole.correct_answer
                hole_form.text_after.data = hole.text_after
                form.text_holes.append_entry(hole_form)
    
    return render_template('edit_exercise.html', form=form, exercise=exercise)

from forms import GradeForm

@app.route('/grade_submission/<int:exercise_id>/<int:submission_id>', methods=['GET', 'POST'])
@login_required
@teacher_required
def grade_submission(exercise_id, submission_id):
    submission = ExerciseSubmission.query.get_or_404(submission_id)
    exercise = Exercise.query.get_or_404(exercise_id)
    
    # Vérifier que l'enseignant est bien le propriétaire de l'exercice
    if exercise.course.class_.teacher_id != current_user.id:
        flash('Vous n\'êtes pas autorisé à noter cet exercice.', 'danger')
        return redirect(url_for('index'))

    form = GradeForm()
    
    if form.validate_on_submit():
        submission.score = form.score.data
        submission.feedback = form.feedback.data
        db.session.commit()
        flash('Note enregistrée avec succès!', 'success')
        return redirect(url_for('view_exercise', exercise_id=exercise_id))

    # Pré-remplir le formulaire avec les valeurs existantes
    if submission.score is not None:
        form.score.data = submission.score
    if hasattr(submission, 'feedback') and submission.feedback:
        form.feedback.data = submission.feedback

    # Pour un QCM, calculer le score automatiquement
    if exercise.exercise_type == 'qcm':
        correct_answers = 0
        total_questions = len(exercise.questions)
        
        for question in exercise.questions:
            answer_key = f'question_{question.id}'
            if answer_key in submission.answers:
                student_choice = submission.answers[answer_key]
                correct_choice = next((choice for choice in question.choices if choice.is_correct), None)
                if correct_choice and student_choice == correct_choice.id:
                    correct_answers += 1
        
        suggested_score = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
        if submission.score is None:
            form.score.data = suggested_score

    return render_template('grade_submission.html', 
                         exercise=exercise, 
                         submission=submission, 
                         form=form)

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', title='Profil')

@app.route('/classes/<int:class_id>')
@login_required
def view_class(class_id):
    class_ = Class.query.get_or_404(class_id)
    
    # Vérifier si l'utilisateur est autorisé à voir cette classe
    if not current_user.is_teacher:
        # Pour les étudiants, vérifier s'ils sont inscrits dans la classe
        enrollment = ClassEnrollment.query.filter_by(
            student_id=current_user.id,
            class_id=class_id
        ).first()
        if not enrollment:
            flash('Vous n\'êtes pas inscrit dans cette classe.', 'danger')
            return redirect(url_for('student_dashboard'))
    elif class_.teacher_id != current_user.id:
        flash('Vous n\'êtes pas l\'enseignant de cette classe.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    # Récupérer tous les exercices associés à la classe
    exercises = Exercise.query.join(ClassExercise).filter(ClassExercise.class_id == class_id).all()
    
    # Récupérer les étudiants inscrits
    enrolled_students = ClassEnrollment.query.filter_by(class_id=class_id).all()
    
    return render_template('view_class.html', 
                         class_=class_,
                         exercises=exercises,
                         enrolled_students=enrolled_students,
                         title=class_.name)

@app.route('/class/<int:class_id>/edit', methods=['GET', 'POST'])
@login_required
@teacher_required
def edit_class(class_id):
    class_ = Class.query.get_or_404(class_id)
    if not current_user.is_teacher or class_.teacher != current_user:
        flash('Vous n\'avez pas la permission de modifier cette classe.', 'danger')
        return redirect(url_for('index'))
    
    form = ClassForm()
    if form.validate_on_submit():
        class_.name = form.name.data
        class_.description = form.description.data
        db.session.commit()
        log_request_info(request)
        log_form_data(request.form.to_dict(), 'edit_class')
        logger.info(f"Class updated successfully with ID: {class_id}")
        flash('La classe a été mise à jour avec succès!', 'success')
        return redirect(url_for('view_class', class_id=class_.id))
    elif request.method == 'GET':
        form.name.data = class_.name
        form.description.data = class_.description
    
    return render_template('edit_class.html', title='Modifier la Classe', form=form, class_=class_)

@app.route('/class/<int:class_id>/delete', methods=['POST'])
@login_required
@teacher_required
def delete_class(class_id):
    if not current_user.is_teacher:
        flash('Seuls les enseignants peuvent supprimer des classes.', 'danger')
        return redirect(url_for('index'))

    class_ = Class.query.get_or_404(class_id)
    
    if class_.teacher_id != current_user.id:
        flash('Vous n\'avez pas l\'autorisation de supprimer cette classe.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    try:
        # Supprimer le dossier des fichiers de la classe s'il existe
        class_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'class_{class_id}')
        if os.path.exists(class_folder):
            shutil.rmtree(class_folder)
        
        # Supprimer la classe de la base de données
        db.session.delete(class_)
        db.session.commit()
        
        log_request_info(request)
        logger.info(f"Class deleted successfully with ID: {class_id}")
        flash('La classe a été supprimée avec succès.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la suppression de la classe {class_id}: {str(e)}")
        flash('Une erreur est survenue lors de la suppression de la classe.', 'danger')
        app.logger.error(f'Erreur lors de la suppression de la classe {class_id}: {str(e)}')

    return redirect(url_for('teacher_dashboard'))

@app.route('/class/<int:class_id>/remove-student/<int:student_id>', methods=['POST'])
@login_required
@teacher_required
def remove_student_from_class(class_id, student_id):
    if current_user.role != 'teacher':
        flash('Seuls les enseignants peuvent retirer des étudiants.', 'danger')
        return redirect(url_for('view_class', class_id=class_id))
    
    class_obj = Class.query.get_or_404(class_id)
    if class_obj.teacher_id != current_user.id:
        flash('Vous n\'êtes pas l\'enseignant de cette classe.', 'danger')
        return redirect(url_for('view_class', class_id=class_id))
    
    enrollment = ClassEnrollment.query.filter_by(
        student_id=student_id,
        class_id=class_id
    ).first_or_404()
    
    try:
        db.session.delete(enrollment)
        db.session.commit()
        log_request_info(request)
        logger.info(f"Student removed from class with ID: {class_id}")
        flash('Étudiant retiré de la classe avec succès.', 'success')
    except Exception as e:
        log_database_error(e, "remove_student_from_class route")
        db.session.rollback()
        flash('Erreur lors de la suppression de l\'étudiant.', 'danger')
        print(f"Error removing student: {str(e)}")
    
    return redirect(url_for('view_class', class_id=class_id))

@app.route('/course/<int:course_id>/upload-file', methods=['POST'])
@login_required
@teacher_required
def upload_course_file(course_id):
    course = Course.query.get_or_404(course_id)
    if current_user != course.class_.teacher:
        flash('Vous n\'avez pas la permission d\'ajouter des fichiers à ce cours.', 'danger')
        return redirect(url_for('view_course', course_id=course_id))
    
    if 'file' not in request.files:
        flash('Aucun fichier sélectionné.', 'danger')
        return redirect(url_for('view_course', course_id=course_id))
    
    file = request.files['file']
    if file.filename == '':
        flash('Aucun fichier sélectionné.', 'danger')
        return redirect(url_for('view_course', course_id=course_id))
    
    if file and allowed_file(file.filename):
        # Sécuriser le nom du fichier
        filename = secure_filename(file.filename)
        # Créer un nom de fichier unique
        unique_filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{filename}"
        # Sauvegarder le fichier
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        
        # Créer l'entrée dans la base de données
        course_file = CourseFile(
            filename=filename,
            file_path=unique_filename,
            course_id=course_id
        )
        db.session.add(course_file)
        db.session.commit()
        
        log_request_info(request)
        logger.info(f"File uploaded successfully to course with ID: {course_id}")
        flash('Le fichier a été téléchargé avec succès.', 'success')
    else:
        flash('Type de fichier non autorisé.', 'danger')
    
    return redirect(url_for('view_course', course_id=course_id))

@app.route('/upload/image/<int:course_id>', methods=['POST'])
@login_required
@teacher_required
def upload_image(course_id):
    # CKEditor envoie le fichier avec le paramètre 'upload'
    if 'upload' not in request.files and 'file' not in request.files:
        return jsonify({'error': 'Aucun fichier n\'a été envoyé'}), 400
    
    # Accepter soit 'upload' (CKEditor) soit 'file' (formulaire standard)
    file = request.files.get('upload') or request.files.get('file')
    if file.filename == '':
        return jsonify({'error': 'Aucun fichier sélectionné'}), 400
        
    if file and allowed_file(file.filename, {'png', 'jpg', 'jpeg', 'gif'}):
        # Générer un nom de fichier unique
        filename = secure_filename(file.filename)
        unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'images', unique_filename)
        
        # Créer le dossier images s'il n'existe pas
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        file.save(file_path)
        
        # Créer une nouvelle image dans la base de données
        image = Image(
            filename=unique_filename,
            course_id=course_id,
            path=f'uploads/images/{unique_filename}'
        )
        db.session.add(image)
        db.session.commit()
        
        # Retourner l'URL de l'image dans le format attendu par CKEditor
        return jsonify({
            'url': url_for('static', filename=f'uploads/images/{unique_filename}', _external=True)
        })
    
    return jsonify({'error': 'Type de fichier non autorisé'}), 400

@app.route('/exercises/<int:exercise_id>/image')
@login_required
def view_exercise_image(exercise_id):
    exercise = Exercise.query.get_or_404(exercise_id)
    if not exercise.image_path:
        return jsonify({'error': 'Aucune image trouvée'}), 404
    
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], exercise.image_path)
    if not os.path.exists(image_path):
        return jsonify({'error': 'Image non trouvée'}), 404
    
    return send_from_directory(os.path.dirname(image_path), os.path.basename(image_path))

@app.route('/create_polygon_exercise/<int:course_id>')
@login_required
@teacher_required
def create_polygon_exercise(course_id):
    try:
        # Créer un nouvel exercice
        exercise = Exercise(
            title='Le nom des polygones',
            description='Complète avec la bonne étiquette.',
            exercise_type='mots_a_placer',
            difficulty='facile',
            points=10,
            course_id=course_id,
            created_date=datetime.utcnow(),
            teacher_id=current_user.id,  # Ajout du teacher_id
            is_in_library=True
        )
        
        db.session.add(exercise)
        db.session.commit()
        
        flash('Exercice sur les polygones créé avec succès!', 'success')
        return redirect(url_for('view_course', course_id=course_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la création de l'exercice: {str(e)}")
        flash('Erreur lors de la création de l\'exercice.', 'danger')
        return redirect(url_for('view_course', course_id=course_id))

@app.route('/delete_student/<int:student_id>', methods=['POST'])
@login_required
@teacher_required
def delete_student(student_id):
    try:
        # Supprimer d'abord les soumissions de l'étudiant
        ExerciseSubmission.query.filter_by(student_id=student_id).delete()
        
        # Supprimer les inscriptions aux classes
        ClassEnrollment.query.filter_by(student_id=student_id).delete()
        
        # Supprimer l'utilisateur
        student = User.query.get_or_404(student_id)
        db.session.delete(student)
        db.session.commit()
        
        flash('Étudiant supprimé avec succès.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Erreur lors de la suppression de l\'étudiant.', 'danger')
        logger.error(f"Erreur lors de la suppression de l'étudiant {student_id}: {str(e)}")
    
    return redirect(url_for('manage_students'))

@app.route("/debug/exercises")
@login_required
def debug_exercises():
    exercises = Exercise.query.all()
    result = []
    for ex in exercises:
        result.append({
            "id": ex.id,
            "title": ex.title,
            "created_by": ex.created_by,
            "course_id": ex.course_id
        })
    return jsonify(result)

@app.route("/debug/exercise/<int:exercise_id>")
@login_required
def debug_exercise(exercise_id):
    exercise = Exercise.query.get(exercise_id)
    if exercise is None:
        return jsonify({
            "exists": False,
            "message": "Exercise not found"
        })
    return jsonify({
        "exists": True,
        "id": exercise.id,
        "title": exercise.title,
        "created_by": exercise.created_by,
        "course_id": exercise.course_id
    })

@app.route('/debug/submissions/<int:exercise_id>')
@login_required
def debug_submissions(exercise_id):
    exercise = Exercise.query.get_or_404(exercise_id)
    submissions = ExerciseSubmission.query.filter_by(exercise_id=exercise_id).all()
    
    debug_info = {
        'exercise_id': exercise_id,
        'exercise_type': exercise.exercise_type,
        'submissions': []
    }
    
    for submission in submissions:
        sub_info = {
            'id': submission.id,
            'student': submission.submitting_student.username,
            'submitted_at': submission.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
            'score': submission.score,
            'answers': submission.answers
        }
        debug_info['submissions'].append(sub_info)
    
    return jsonify(debug_info)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Vérifier si l'utilisateur admin existe déjà
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='jematali@gmail.com',
                role='teacher'
            )
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()
            print("Utilisateur admin créé avec succès!")
            
    app.run(debug=True)
