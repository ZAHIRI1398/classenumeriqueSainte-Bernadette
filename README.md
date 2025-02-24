# Classe Numérique

Une plateforme éducative pour les enseignants et les élèves, permettant la création et la gestion d'exercices interactifs.

## Fonctionnalités

### Pour les enseignants
- Création et gestion de classes
- Création d'exercices personnalisés
- Suivi des progrès des élèves
- Attribution d'exercices aux classes

### Pour les élèves
- Accès aux exercices de leurs classes
- Réalisation des exercices en ligne
- Consultation de leurs résultats

### Bibliothèque d'exercices
- **Mathématiques**
  - Nombres et opérations
  - Solides et figures
  - Grandeurs
- **Français**
  - Grammaire
  - Conjugaison
  - Orthographe
  - Vocabulaire
  - Lecture/Écriture
  - Littérature
- **Autres matières**
  - Éveil
  - Sciences

### Types d'exercices
- QCM (Questions à choix multiples)
- Questions ouvertes
- Textes à trous

## Installation

1. Installer Python (version 3.8 ou supérieure)

2. Cloner le projet :
```bash
git clone https://github.com/votre-nom/classe-numerique.git
cd classe-numerique
```

3. Créer et activer l'environnement virtuel :
```bash
# Windows
python -m venv venv
venv\Scripts\activate
```

4. Installer les dépendances :
```bash
pip install -r requirements.txt
```

5. Initialiser la base de données :
```bash
python reset_db.py
```

6. Lancer l'application :
```bash
python app.py
```

7. Accéder à l'application dans votre navigateur :
```
http://localhost:5000
```

## Utilisation

### Première utilisation
1. Créer un compte enseignant
2. Se connecter avec les identifiants
3. Créer une ou plusieurs classes
4. Créer des exercices
5. Attribuer les exercices aux classes

### Pour les élèves
1. Créer un compte élève
2. Se connecter avec les identifiants
3. Rejoindre une classe avec le code fourni par l'enseignant
4. Accéder aux exercices de la classe
5. Réaliser les exercices

## Base de données

La base de données SQLite contient les tables suivantes :
- **Users** : Utilisateurs (enseignants et élèves)
- **Classes** : Classes créées par les enseignants
- **ClassEnrollments** : Inscriptions des élèves aux classes
- **Exercises** : Exercices avec leurs métadonnées
- **Questions** : Questions des exercices
- **Choices** : Options pour les QCM
- **TextHoles** : Trous pour les exercices de type texte à trous
- **ExerciseSubmissions** : Réponses des élèves

## Développement

### Réinitialiser la base de données
Pour repartir de zéro :
```bash
python reset_db.py
```

### Structure du projet
- `app.py` : Application principale Flask
- `models.py` : Modèles de la base de données
- `forms.py` : Formulaires WTForms
- `templates/` : Templates HTML
- `static/` : Fichiers statiques (CSS, JS, images)

## Technologies
- **Backend** : Flask (Python)
- **Base de données** : SQLite avec SQLAlchemy
- **Frontend** : 
  - HTML/CSS avec Bootstrap 5
  - JavaScript
  - Font Awesome pour les icônes
- **Sécurité** :
  - Flask-Login pour l'authentification
  - WTForms pour la validation des formulaires
  - Protection CSRF
