from datetime import datetime
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from models import User, SchoolYear, Assessment, School, Class, AuditLog
from services.doelen import load_index, load_vak, is_valid_vak_id
from services.audit import audit_log
from functools import wraps
from app import db, limiter

api_bp = Blueprint('api', __name__)


def director_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_director:
            return jsonify({'error': 'Geen toegang'}), 403
        return f(*args, **kwargs)
    return decorated


def get_active_year():
    """Geeft het globaal actief schooljaar terug."""
    return SchoolYear.query.filter_by(school_id=None, is_active=True).first()


def check_class_access(class_id):
    """
    Geeft de klas terug als de huidige gebruiker er toegang toe heeft.
    - Leerkrachten: enkel hun eigen klassen (via teacher_classes).
    - Directeur en hoger: alle klassen van hun school.
    - Geeft False terug als de klas niet bestaat.
    - Geeft None terug als de gebruiker geen toegang heeft.
    """
    klas = Class.query.filter_by(id=class_id).first()
    if not klas:
        return False
    if klas.school_id != current_user.school_id:
        return None
    if current_user.is_teacher:
        if not any(c.id == class_id for c in current_user.classes):
            return None
    return klas


# ── Doelen (statische JSON bestanden) ─────────────────────────────────────────

@api_bp.route('/doelen/index')
@login_required
def doelen_index():
    data = load_index()
    return jsonify(data)


@api_bp.route('/doelen/<vak_id>')
@login_required
def doelen_vak(vak_id):
    if not is_valid_vak_id(vak_id):
        return jsonify({'error': 'Ongeldig vak ID'}), 400
    data = load_vak(vak_id)
    if not data:
        return jsonify({'error': f'Vak "{vak_id}" niet gevonden'}), 404
    return jsonify(data)


# ── Beoordelingen ─────────────────────────────────────────────────────────────

@api_bp.route('/assessments', methods=['GET'])
@login_required
def get_assessments():
    """Haal beoordelingen op voor een klas (en optioneel een vak)."""
    class_id_str = request.args.get('class_id')
    if not class_id_str:
        return jsonify({'assessments': []})

    try:
        class_id = int(class_id_str)
    except ValueError:
        return jsonify({'error': 'Ongeldig class_id'}), 400

    klas = check_class_access(class_id)
    if klas is False:
        return jsonify({'error': 'Klas niet gevonden'}), 404
    if klas is None:
        return jsonify({'error': 'Geen toegang tot deze klas'}), 403

    school_year = get_active_year()
    if not school_year:
        return jsonify({'assessments': []})

    year_id = request.args.get('year_id', school_year.id)
    vak_id  = request.args.get('vak_id')

    query = Assessment.query.filter_by(class_id=class_id, school_year_id=year_id)
    if vak_id:
        query = query.filter_by(vak_id=vak_id)

    return jsonify({'assessments': [a.to_dict() for a in query.all()]})


@api_bp.route('/assessments', methods=['POST'])
@login_required
@limiter.limit('120 per minute')
def save_assessment():
    data      = request.get_json() or {}
    class_id  = data.get('class_id')
    vak_id    = (data.get('vak_id') or '').strip()
    goal_id   = (data.get('goal_id') or '').strip()
    status    = (data.get('status') or '').strip()
    opmerking = (data.get('opmerking') or '').strip()[:500]

    if not class_id or not vak_id or not goal_id:
        return jsonify({'error': 'class_id, vak_id en goal_id zijn verplicht'}), 400
    if status not in ('groen', 'oranje', 'roze', ''):
        return jsonify({'error': 'Ongeldige status'}), 400
    if len(vak_id) > 100 or len(goal_id) > 50:
        return jsonify({'error': 'Ongeldige invoer'}), 400

    try:
        class_id = int(class_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'Ongeldig class_id'}), 400

    klas = check_class_access(class_id)
    if klas is False:
        return jsonify({'error': 'Klas niet gevonden'}), 404
    if klas is None:
        return jsonify({'error': 'Geen toegang tot deze klas'}), 403

    school_year = get_active_year()
    if not school_year:
        return jsonify({'error': 'Geen actief schooljaar gevonden'}), 400

    assessment = Assessment.query.filter_by(
        class_id=class_id,
        school_year_id=school_year.id,
        vak_id=vak_id,
        goal_id=goal_id,
    ).first()

    if status == '':
        if assessment:
            db.session.delete(assessment)
            db.session.commit()
        return jsonify({'deleted': True})

    if assessment:
        assessment.status     = status
        assessment.opmerking  = opmerking or None
        assessment.updated_at = datetime.utcnow()
    else:
        assessment = Assessment(
            class_id=class_id,
            school_year_id=school_year.id,
            vak_id=vak_id,
            goal_id=goal_id,
            status=status,
            opmerking=opmerking or None,
        )
        db.session.add(assessment)

    db.session.commit()
    audit_log('assessment.save', 'assessment',
              target_type='class', target_id=str(class_id),
              detail={'status': status, 'vak': vak_id, 'goal': goal_id})
    return jsonify({'assessment': assessment.to_dict()})


@api_bp.route('/assessments/opmerking', methods=['POST'])
@login_required
@limiter.limit('120 per minute')
def save_opmerking():
    data      = request.get_json() or {}
    class_id  = data.get('class_id')
    vak_id    = (data.get('vak_id') or '').strip()
    goal_id   = (data.get('goal_id') or '').strip()
    opmerking = (data.get('opmerking') or '').strip()[:500]

    if not class_id or not vak_id or not goal_id:
        return jsonify({'error': 'class_id, vak_id en goal_id zijn verplicht'}), 400
    if len(vak_id) > 100 or len(goal_id) > 50:
        return jsonify({'error': 'Ongeldige invoer'}), 400

    try:
        class_id = int(class_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'Ongeldig class_id'}), 400

    klas = check_class_access(class_id)
    if klas is False:
        return jsonify({'error': 'Klas niet gevonden'}), 404
    if klas is None:
        return jsonify({'error': 'Geen toegang tot deze klas'}), 403

    school_year = get_active_year()
    if not school_year:
        return jsonify({'error': 'Geen actief schooljaar'}), 400

    assessment = Assessment.query.filter_by(
        class_id=class_id,
        school_year_id=school_year.id,
        vak_id=vak_id,
        goal_id=goal_id,
    ).first()

    if assessment:
        assessment.opmerking  = opmerking or None
        assessment.updated_at = datetime.utcnow()
    else:
        assessment = Assessment(
            class_id=class_id,
            school_year_id=school_year.id,
            vak_id=vak_id,
            goal_id=goal_id,
            status='',
            opmerking=opmerking or None,
        )
        db.session.add(assessment)

    db.session.commit()
    return jsonify({'ok': True})


@api_bp.route('/assessments/bulk-import', methods=['POST'])
@login_required
@limiter.limit('5 per minute')
def bulk_import_assessments():
    """
    Importeer beoordelingen vanuit legacy standalone JSON export.
    Body: { "class_id": 1, "vakken": { "vak_id": { "goal_id": "status" } } }
    """
    data     = request.get_json() or {}
    class_id = data.get('class_id')
    vakken   = data.get('vakken', {})

    if not class_id:
        return jsonify({'error': 'class_id is verplicht'}), 400
    if not vakken:
        return jsonify({'error': 'Geen vakken gevonden in payload'}), 400

    try:
        class_id = int(class_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'Ongeldig class_id'}), 400

    klas = check_class_access(class_id)
    if klas is False:
        return jsonify({'error': 'Klas niet gevonden'}), 404
    if klas is None:
        return jsonify({'error': 'Geen toegang tot deze klas'}), 403

    school_year = get_active_year()
    if not school_year:
        return jsonify({'error': 'Geen actief schooljaar'}), 400

    totaal = 0
    fouten = 0

    for vak_id, vak_data in vakken.items():
        if not isinstance(vak_id, str) or len(vak_id) > 100:
            fouten += 1
            continue

        # Ondersteun zowel { statussen: {...} } als { goal_id: status }
        if isinstance(vak_data, dict) and 'statussen' in vak_data:
            statussen = vak_data['statussen']
        else:
            statussen = vak_data

        if not isinstance(statussen, dict):
            continue

        for goal_id, status in statussen.items():
            if not isinstance(goal_id, str) or len(goal_id) > 50:
                fouten += 1
                continue
            if status not in ('groen', 'oranje', 'roze'):
                continue

            try:
                assessment = Assessment.query.filter_by(
                    class_id=class_id,
                    school_year_id=school_year.id,
                    vak_id=vak_id,
                    goal_id=goal_id,
                ).first()

                if assessment:
                    assessment.status     = status
                    assessment.updated_at = datetime.utcnow()
                else:
                    db.session.add(Assessment(
                        class_id=class_id,
                        school_year_id=school_year.id,
                        vak_id=vak_id,
                        goal_id=goal_id,
                        status=status,
                    ))
                totaal += 1
            except Exception:
                db.session.rollback()
                fouten += 1

    db.session.commit()
    audit_log('assessment.bulk_import', 'assessment',
              target_type='class', target_id=str(class_id),
              detail={'totaal': totaal, 'fouten': fouten})
    return jsonify({'totaal': totaal, 'fouten': fouten})


# ── Directeur schooloverzicht ──────────────────────────────────────────────────

@api_bp.route('/school/overview')
@login_required
@director_required
def school_overview():
    if not current_user.school_id:
        return jsonify({'error': 'Geen school gekoppeld'}), 400

    school_year = get_active_year()
    if not school_year:
        return jsonify({'error': 'Geen actief schooljaar'}), 400

    year_id_param = request.args.get('year_id')
    if year_id_param:
        selected_year = SchoolYear.query.get(int(year_id_param)) or school_year
    else:
        selected_year = school_year

    vak_id = request.args.get('vak_id')

    # Alle klassen van deze school
    klassen   = Class.query.filter_by(school_id=current_user.school_id)\
                           .order_by(Class.name).all()
    class_ids = [k.id for k in klassen]

    query = Assessment.query.filter(
        Assessment.class_id.in_(class_ids),
        Assessment.school_year_id == selected_year.id,
    )
    if vak_id:
        query = query.filter_by(vak_id=vak_id)

    # Groepeer per klas → vak → goal
    by_class = {k.id: {} for k in klassen}
    for a in query.all():
        by_class[a.class_id].setdefault(a.vak_id, {})[a.goal_id] = a.status

    return jsonify({
        'school_year':          selected_year.to_dict(),
        'classes':              [k.to_dict() for k in klassen],
        'assessments_by_class': by_class,
    })


# ── Gebruikersbeheer (director / school_ict) ───────────────────────────────────

@api_bp.route('/users', methods=['GET'])
@login_required
@director_required
def list_users():
    users = User.query.filter_by(
        school_id=current_user.school_id, is_active=True
    ).order_by(User.last_name, User.first_name).all()
    return jsonify({'users': [u.to_dict() for u in users]})


@api_bp.route('/users', methods=['POST'])
@login_required
@director_required
def create_user():
    data  = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'E-mailadres is verplicht'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'E-mailadres is al in gebruik'}), 409
    user = User(
        email=email,
        first_name=data.get('first_name', '').strip(),
        last_name=data.get('last_name', '').strip(),
        role='teacher',
        school_id=current_user.school_id,
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({'user': user.to_dict()}), 201


@api_bp.route('/users/<int:user_id>', methods=['DELETE'])
@login_required
@director_required
def delete_user(user_id):
    user = User.query.filter_by(
        id=user_id, school_id=current_user.school_id
    ).first_or_404()
    user.is_active = False
    db.session.commit()
    return jsonify({'deleted': True})


# ── Schooljaren ────────────────────────────────────────────────────────────────

@api_bp.route('/school/years')
@login_required
@director_required
def get_school_years():
    years = SchoolYear.query.filter_by(school_id=None)\
                            .order_by(SchoolYear.label.desc()).all()
    return jsonify({'years': [y.to_dict() for y in years]})


# ── Huidig ingelogde gebruiker ─────────────────────────────────────────────────

@api_bp.route('/me')
@login_required
def me():
    school_year = get_active_year() if current_user.school_id else None
    return jsonify({
        'user':        current_user.to_dict(),
        'school_year': school_year.to_dict() if school_year else None,
    })


# ── Klassen voor leerkracht ────────────────────────────────────────────────────

@api_bp.route('/my/classes', methods=['GET'])
@login_required
def my_classes():
    """Geeft alle klassen van de school en de eigen klassen van de leerkracht.
    Directeurs en hoger zien automatisch alle klassen als my_classes."""
    if not current_user.school_id:
        return jsonify({'all_classes': [], 'my_classes': []})
    all_cls = Class.query.filter_by(school_id=current_user.school_id)\
                         .order_by(Class.name).all()
    # Directeurs en hoger hebben toegang tot alle klassen zonder expliciete koppeling
    my_cls = all_cls if current_user.is_director else current_user.classes
    return jsonify({
        'all_classes': [{'id': c.id, 'name': c.name} for c in all_cls],
        'my_classes':  [{'id': c.id, 'name': c.name} for c in my_cls],
    })


@api_bp.route('/my/classes', methods=['PUT'])
@login_required
def set_my_classes():
    """Leerkracht stelt zijn eigen klassen in."""
    data      = request.get_json() or {}
    class_ids = data.get('class_ids', [])
    classes   = Class.query.filter(
        Class.id.in_(class_ids),
        Class.school_id == current_user.school_id,
    ).all()
    current_user.classes = classes
    audit_log('class.user_assignment', 'class', target_type='user',
              target_id=str(current_user.id),
              detail={'class_ids': class_ids, 'class_names': [c.name for c in classes]})
    db.session.commit()
    return jsonify({'my_classes': [{'id': c.id, 'name': c.name} for c in current_user.classes]})




# ── Klassen CRUD (directeur) ───────────────────────────────────────────────────

@api_bp.route('/classes', methods=['GET'])
@login_required
@director_required
def list_classes():
    """Alle klassen van de school."""
    classes = Class.query.filter_by(school_id=current_user.school_id)                         .order_by(Class.name).all()
    return jsonify({'classes': [
        {'id': c.id, 'name': c.name,
         'teachers': [{'id': t.id, 'full_name': t.full_name} for t in c.teachers]}
        for c in classes
    ]})


@api_bp.route('/classes', methods=['POST'])
@login_required
@director_required
def create_class():
    """Nieuwe klas aanmaken."""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Naam is verplicht'}), 400
    if Class.query.filter_by(school_id=current_user.school_id, name=name).first():
        return jsonify({'error': 'Een klas met deze naam bestaat al'}), 409
    klas = Class(name=name, school_id=current_user.school_id)
    db.session.add(klas)
    audit_log('class.create', 'class', detail={'name': name})
    db.session.commit()
    return jsonify({'class': {'id': klas.id, 'name': klas.name, 'teachers': []}}), 201


@api_bp.route('/classes/<int:class_id>', methods=['DELETE'])
@login_required
@director_required
def delete_class(class_id):
    """Klas verwijderen (enkel eigen school)."""
    klas = Class.query.filter_by(id=class_id, school_id=current_user.school_id).first_or_404()
    name = klas.name
    db.session.delete(klas)
    audit_log('class.delete', 'class', target_id=str(class_id), detail={'name': name})
    db.session.commit()
    return jsonify({'deleted': class_id})

# ── Klas-leerkracht koppeling (directeur) ──────────────────────────────────────

@api_bp.route('/classes/<int:class_id>/teachers', methods=['PUT'])
@login_required
@director_required
def set_class_teachers(class_id):
    """Directeur koppelt leerkrachten aan een klas."""
    klas = Class.query.filter_by(id=class_id, school_id=current_user.school_id).first_or_404()
    data     = request.get_json() or {}
    user_ids = data.get('teacher_ids', [])
    teachers = User.query.filter(
        User.id.in_(user_ids),
        User.school_id == current_user.school_id,
        User.is_active == True,
    ).all()
    klas.teachers = teachers
    audit_log('class.user_assignment', 'class', target_id=str(class_id),
              detail={'class_name': klas.name, 'teacher_ids': user_ids,
                      'teacher_names': [t.full_name for t in teachers]})
    db.session.commit()
    return jsonify({'teachers': [{'id': t.id, 'full_name': t.full_name} for t in teachers]})

# ── Auditlog ───────────────────────────────────────────────────────────────────

@api_bp.route('/audit-log')
@login_required
def get_audit_log():
    if not current_user.is_school_ict:
        return jsonify({'error': 'Geen toegang'}), 403

    page     = max(1, int(request.args.get('page', 1)))
    per_page = min(100, max(1, int(request.args.get('per_page', 50))))
    category = request.args.get('category')
    search   = request.args.get('search', '').strip()

    query = AuditLog.query
    if not current_user.is_scholengroep_ict:
        query = query.filter(AuditLog.school_id == current_user.school_id)
    if category:
        query = query.filter(AuditLog.category == category)
    if search:
        query = query.filter(
            db.or_(
                AuditLog.action.ilike(f'%{search}%'),
                AuditLog.detail.ilike(f'%{search}%'),
            )
        )

    total   = query.count()
    entries = query.order_by(AuditLog.timestamp.desc())\
                   .offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'total':   total,
        'page':    page,
        'pages':   (total + per_page - 1) // per_page,
        'entries': [e.to_dict() for e in entries],
    })


# ── SSO-lookup ─────────────────────────────────────────────────────────────────

@api_bp.route('/sso-lookup')
def sso_lookup():
    from flask import current_app

    email = request.args.get('email', '').lower().strip()
    if not email or '@' not in email:
        return jsonify({'error': 'Ongeldig e-mailadres'}), 400

    domain  = email.split('@')[-1]
    schools = School.query.all()
    school  = next(
        (s for s in schools if s.email_domains and domain in [d.lower() for d in s.email_domains]),
        None
    )

    microsoft_available = bool(
        current_app.config.get('MICROSOFT_CLIENT_ID') and
        current_app.config.get('MICROSOFT_CLIENT_SECRET')
    )

    if not school:
        return jsonify({'found': False, 'microsoft': microsoft_available, 'google': False})

    return jsonify({
        'found':       True,
        'school_id':   school.id,
        'school_name': school.name,
        'microsoft':   microsoft_available,
        'google':      bool(school.google_client_id and school.google_client_secret),
    })
