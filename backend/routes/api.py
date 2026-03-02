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


def get_active_year(school_id=None):
    """Geeft het globaal actief schooljaar terug (school_id wordt genegeerd)."""
    return SchoolYear.query.filter_by(school_id=None, is_active=True).first()


# ── Doelen (statische JSON bestanden) ─────────────────────────────────────────

@api_bp.route('/doelen/index')
@login_required
def doelen_index():
    data = load_index()
    # Altijd een geldig object teruggeven — lege vakkenlijst is geen fout
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
    if not current_user.school_id:
        return jsonify({'assessments': []})
    school_year = get_active_year(current_user.school_id)
    if not school_year:
        return jsonify({'assessments': []})

    year_id = request.args.get('year_id', school_year.id)
    vak_id  = request.args.get('vak_id')

    query = Assessment.query.filter_by(user_id=current_user.id, school_year_id=year_id)
    if vak_id:
        query = query.filter_by(vak_id=vak_id)

    return jsonify({'assessments': [a.to_dict() for a in query.all()]})


@api_bp.route('/assessments', methods=['POST'])
@login_required
@limiter.limit('120 per minute')  # max 2 per seconde per gebruiker
def save_assessment():
    data    = request.get_json() or {}
    vak_id  = (data.get('vak_id') or '').strip()
    goal_id = (data.get('goal_id') or '').strip()
    status  = (data.get('status') or '').strip()

    if not vak_id or not goal_id:
        return jsonify({'error': 'vak_id en goal_id zijn verplicht'}), 400
    if status not in ('groen', 'oranje', 'roze', ''):
        return jsonify({'error': 'Ongeldige status — gebruik groen, oranje, roze of leeg'}), 400
    # Sanitiseer input — voorkomt oversized data in DB
    if len(vak_id) > 100 or len(goal_id) > 50:
        return jsonify({'error': 'Ongeldige invoer'}), 400
    if not current_user.school_id:
        return jsonify({'error': 'Account is nog niet gekoppeld aan een school'}), 400

    school_year = get_active_year(current_user.school_id)
    if not school_year:
        return jsonify({'error': 'Geen actief schooljaar gevonden'}), 400

    assessment = Assessment.query.filter_by(
        user_id=current_user.id,
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
        assessment.updated_at = datetime.utcnow()
    else:
        assessment = Assessment(
            user_id=current_user.id,
            school_id=current_user.school_id,
            school_year_id=school_year.id,
            vak_id=vak_id,
            goal_id=goal_id,
            status=status,
        )
        db.session.add(assessment)

    db.session.commit()
    # Auditlog enkel bij statuswijziging (niet bij elke klik)
    audit_log('assessment.save', 'assessment',
              target_type='goal', target_id=f'{vak_id}:{goal_id}',
              detail={'status': status})
    return jsonify({'assessment': assessment.to_dict()})


@api_bp.route('/assessments/bulk-import', methods=['POST'])
@login_required
@limiter.limit('5 per minute')
def bulk_import_assessments():
    """
    Importeer beoordelingen vanuit de legacy standalone JSON export.
    Body: { "vakken": { "vak_id": { "goal_id": "status", ... }, ... } }
    of v4 formaat: { "vakken": { "vak_id": { "statussen": { "goal_id": "status" } } } }
    """
    if not current_user.school_id:
        return jsonify({'error': 'Account niet gekoppeld aan een school'}), 400

    school_year = get_active_year(current_user.school_id)
    if not school_year:
        return jsonify({'error': 'Geen actief schooljaar'}), 400

    data   = request.get_json() or {}
    vakken = data.get('vakken', {})
    if not vakken:
        return jsonify({'error': 'Geen vakken gevonden in payload'}), 400

    totaal = 0
    fouten = 0

    for vak_id, vak_data in vakken.items():
        # Sanitiseer vak_id
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
                    user_id=current_user.id,
                    school_year_id=school_year.id,
                    vak_id=vak_id,
                    goal_id=goal_id,
                ).first()

                if assessment:
                    assessment.status     = status
                    assessment.updated_at = datetime.utcnow()
                else:
                    db.session.add(Assessment(
                        user_id=current_user.id,
                        school_id=current_user.school_id,
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
              detail={'totaal': totaal, 'fouten': fouten})
    return jsonify({'totaal': totaal, 'fouten': fouten})


# ── Directeur schooloverzicht ──────────────────────────────────────────────────

@api_bp.route('/school/overview')
@login_required
@director_required
def school_overview():
    if not current_user.school_id:
        return jsonify({'error': 'Geen school gekoppeld'}), 400
    school_year = get_active_year(current_user.school_id)
    if not school_year:
        return jsonify({'error': 'Geen actief schooljaar'}), 400

    # year_id param: directeur/admin kan wisselen, leerkracht zit vast aan actief jaar
    year_id_param = request.args.get('year_id')
    if year_id_param and current_user.is_director:
        year_id = int(year_id_param)
        selected_year = SchoolYear.query.filter_by(
            id=year_id, school_id=current_user.school_id
        ).first() or school_year
    else:
        selected_year = school_year
        year_id       = school_year.id

    vak_id  = request.args.get('vak_id')

    teachers = User.query.filter_by(
        school_id=current_user.school_id, role='teacher', is_active=True
    ).all()

    query = Assessment.query.filter_by(
        school_id=current_user.school_id, school_year_id=year_id
    )
    if vak_id:
        query = query.filter_by(vak_id=vak_id)

    by_teacher = {t.id: {} for t in teachers}
    for a in query.all():
        by_teacher.setdefault(a.user_id, {})
        by_teacher[a.user_id].setdefault(a.vak_id, {})
        by_teacher[a.user_id][a.vak_id][a.goal_id] = a.status

    return jsonify({
        'school_year':            selected_year.to_dict(),
        'teachers':               [t.to_dict() for t in teachers],
        'assessments_by_teacher': by_teacher,
    })


# ── Gebruikersbeheer (school_ict / directeur) ──────────────────────────────────

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



# ── Schooljaren (directeur/admin leesbaar) ────────────────────────────────────

@api_bp.route('/school/years')
@login_required
@director_required
def get_school_years():
    """Geeft alle globale schooljaren terug (voor jaarselectie in directeur dashboard)."""
    years = SchoolYear.query.filter_by(school_id=None)                            .order_by(SchoolYear.label.desc()).all()
    return jsonify({'years': [y.to_dict() for y in years]})


# ── Huidig ingelogde gebruiker ────────────────────────────────────────────────

@api_bp.route('/me')
@login_required
def me():
    school_year = get_active_year(current_user.school_id) if current_user.school_id else None
    return jsonify({
        'user':        current_user.to_dict(),
        'school_year': school_year.to_dict() if school_year else None,
    })


# ── Klassen voor leerkracht (zelf instellen) ──────────────────────────────────

@api_bp.route('/my/classes', methods=['GET'])
@login_required
def my_classes():
    """Geeft alle beschikbare klassen en eigen klassen terug."""
    if not current_user.school_id:
        return jsonify({'all_classes': [], 'my_classes': []})
    all_cls = Class.query.filter_by(school_id=current_user.school_id)                         .order_by(Class.name).all()
    return jsonify({
        'all_classes': [{'id': c.id, 'name': c.name} for c in all_cls],
        'my_classes':  [{'id': c.id, 'name': c.name} for c in current_user.classes],
    })


@api_bp.route('/my/classes', methods=['PUT'])
@login_required
def set_my_classes():
    """Leerkracht stelt eigen klassen in."""
    data      = request.get_json() or {}
    class_ids = data.get('class_ids', [])
    classes   = Class.query.filter(
        Class.id.in_(class_ids),
        Class.school_id == current_user.school_id
    ).all()
    current_user.classes = classes
    audit_log('class.user_assignment', 'class', target_type='user',
              target_id=str(current_user.id),
              detail={'class_ids': class_ids, 'class_names': [c.name for c in classes]})
    db.session.commit()
    return jsonify({'my_classes': [{'id': c.id, 'name': c.name} for c in current_user.classes]})



# ── Auditlog ──────────────────────────────────────────────────────────────────

@api_bp.route('/audit-log')
@login_required
def get_audit_log():
    if not current_user.is_school_ict:
        return jsonify({'error': 'Geen toegang'}), 403

    page      = max(1, int(request.args.get('page', 1)))
    per_page  = min(100, max(1, int(request.args.get('per_page', 50))))  # max 100 per pagina
    category  = request.args.get('category')
    search    = request.args.get('search', '').strip()

    query = AuditLog.query

    # School ICT ziet enkel eigen school
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
    entries = query.order_by(AuditLog.timestamp.desc())                   .offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'total':   total,
        'page':    page,
        'pages':   (total + per_page - 1) // per_page,
        'entries': [e.to_dict() for e in entries],
    })

