"""
Admin routes

Toegang per rol:
  superadmin        → alles
  scholengroep_ict  → scholen + gebruikers beheren, doelen uploaden
  school_ict        → leerkrachten en klassen van eigen school beheren
"""

import re
import json as jsonlib
from flask import Blueprint, jsonify, request
from services.audit import audit_log
from flask_login import login_required, current_user
from models import User, School, SchoolYear, Class, TeacherClass
from app import db
from functools import wraps

admin_bp = Blueprint('admin', __name__)

VALID_ROLES = ('superadmin', 'scholengroep_ict', 'school_ict', 'director', 'teacher')


# ── Toegangsdecorators ────────────────────────────────────────────────────────

def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_superadmin:
            return jsonify({'error': 'Geen toegang — superadmin vereist'}), 403
        return f(*args, **kwargs)
    return decorated

def scholengroep_ict_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_scholengroep_ict:
            return jsonify({'error': 'Geen toegang — scholengroep ICT vereist'}), 403
        return f(*args, **kwargs)
    return decorated

def school_ict_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_school_ict:
            return jsonify({'error': 'Geen toegang — school ICT vereist'}), 403
        return f(*args, **kwargs)
    return decorated


# ── Scholen (scholengroep_ict) ────────────────────────────────────────────────

@admin_bp.route('/schools', methods=['GET'])
@login_required
@scholengroep_ict_required
def list_schools():
    schools = School.query.order_by(School.name).all()
    result = []
    for s in schools:
        d = s.to_dict()
        d['user_count'] = User.query.filter_by(school_id=s.id, is_active=True).count()
        result.append(d)
    return jsonify({'schools': result})


@admin_bp.route('/schools', methods=['POST'])
@login_required
@scholengroep_ict_required
def create_school():
    data    = request.get_json() or {}
    name    = data.get('name', '').strip()
    slug    = data.get('slug', '').strip().lower()
    domains = [d.strip().lower() for d in data.get('email_domains', []) if d.strip()]

    if not name:
        return jsonify({'error': 'Naam is verplicht'}), 400
    if not slug:
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    if School.query.filter_by(slug=slug).first():
        return jsonify({'error': f'Slug "{slug}" is al in gebruik'}), 409

    school = School(name=name, slug=slug, email_domains=domains)
    db.session.add(school)
    db.session.flush()
    audit_log('school.create', 'school', target_type='school', target_id=str(school.id),
              detail={'name': name, 'slug': slug}, school_id=school.id)
    db.session.commit()
    return jsonify({'school': school.to_dict()}), 201


@admin_bp.route('/schools/<int:school_id>', methods=['PUT'])
@login_required
@scholengroep_ict_required
def update_school(school_id):
    school = School.query.get_or_404(school_id)
    data   = request.get_json() or {}
    if 'name' in data:
        school.name = data['name'].strip()
    if 'email_domains' in data:
        school.email_domains = [d.strip().lower() for d in data['email_domains'] if d.strip()]
    db.session.commit()
    return jsonify({'school': school.to_dict()})


@admin_bp.route('/schools/<int:school_id>', methods=['DELETE'])
@login_required
@scholengroep_ict_required
def delete_school(school_id):
    school = School.query.get_or_404(school_id)
    school_name = school.name
    try:
        audit_log('school.delete', 'school', target_type='school', target_id=str(school_id),
                  detail={'name': school_name}, school_id=school_id)
        db.session.flush()
        db.session.execute(
            db.text("DELETE FROM schools WHERE id = :id"),
            {"id": school_id}
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Verwijderen mislukt: {str(e)}'}), 500
    return jsonify({'deleted': True})



# ── Schooljaren (globaal — niet per school) ──────────────────────────────────

@admin_bp.route('/years', methods=['GET'])
@login_required
@school_ict_required
def list_years():
    """Alle globale schooljaren, nieuwste eerst."""
    years = SchoolYear.query.filter_by(school_id=None)                            .order_by(SchoolYear.label.desc()).all()
    return jsonify({'years': [y.to_dict() for y in years]})


@admin_bp.route('/years', methods=['POST'])
@login_required
@scholengroep_ict_required
def create_year():
    """Maak een nieuw globaal schooljaar aan."""
    data  = request.get_json() or {}
    label = data.get('label', '').strip()

    if not label:
        return jsonify({'error': 'Label is verplicht (bv. 2025-2026)'}), 400
    if SchoolYear.query.filter_by(label=label).first():
        return jsonify({'error': f'Schooljaar {label} bestaat al'}), 409

    if data.get('set_active', True):
        SchoolYear.query.filter_by(school_id=None, is_active=True)                        .update({'is_active': False})

    year = SchoolYear(school_id=None, label=label,
                      is_active=data.get('set_active', True))
    db.session.add(year)
    db.session.flush()
    audit_log('year.create', 'system', target_type='school_year', target_id=str(year.id),
              detail={'label': label, 'active': year.is_active})
    db.session.commit()
    return jsonify({'year': year.to_dict()}), 201


@admin_bp.route('/years/<int:year_id>/activate', methods=['PUT'])
@login_required
@scholengroep_ict_required
def activate_year(year_id):
    """Zet een schooljaar als actief (deactiveert de rest)."""
    year = SchoolYear.query.filter_by(id=year_id, school_id=None).first_or_404()
    SchoolYear.query.filter_by(school_id=None, is_active=True)                    .update({'is_active': False})
    year.is_active = True
    audit_log('year.activate', 'system', target_type='school_year', target_id=str(year_id),
              detail={'label': year.label})
    db.session.commit()
    return jsonify({'year': year.to_dict()})


# ── Gebruikers per school ─────────────────────────────────────────────────────

@admin_bp.route('/schools/<int:school_id>/users', methods=['GET'])
@login_required
@school_ict_required
def list_school_users(school_id):
    if not current_user.is_scholengroep_ict and current_user.school_id != school_id:
        return jsonify({'error': 'Geen toegang tot deze school'}), 403
    users = User.query.filter_by(school_id=school_id, is_active=True)\
                      .order_by(User.last_name, User.first_name).all()
    return jsonify({'users': [u.to_dict() for u in users]})


@admin_bp.route('/schools/<int:school_id>/users', methods=['POST'])
@login_required
@school_ict_required
def add_user_to_school(school_id):
    if not current_user.is_scholengroep_ict and current_user.school_id != school_id:
        return jsonify({'error': 'Geen toegang tot deze school'}), 403

    School.query.get_or_404(school_id)
    data  = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    role  = data.get('role', 'teacher')

    if not email:
        return jsonify({'error': 'E-mailadres is verplicht'}), 400

    allowed_roles = ('teacher', 'director', 'school_ict')
    if current_user.role == 'school_ict' and role not in allowed_roles:
        return jsonify({'error': f'Rol "{role}" mag niet worden toegewezen door school ICT'}), 403
    if role not in VALID_ROLES:
        return jsonify({'error': f'Ongeldige rol: {role}'}), 400

    existing = User.query.filter_by(email=email).first()
    if existing:
        # Account bestaat al (ook als uitgeschakeld) — activeer en update rol/school
        existing.school_id = school_id
        existing.role      = role
        existing.is_active = True
        db.session.commit()
        return jsonify({'user': existing.to_dict(), 'linked': True})

    user = User(
        email=email,
        first_name=data.get('first_name', '').strip(),
        last_name=data.get('last_name', '').strip(),
        role=role,
        school_id=school_id,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({'user': user.to_dict(), 'linked': False}), 201


@admin_bp.route('/schools/<int:school_id>/users/<int:user_id>/role', methods=['PUT'])
@login_required
@school_ict_required
def update_user_role(school_id, user_id):
    if not current_user.is_scholengroep_ict and current_user.school_id != school_id:
        return jsonify({'error': 'Geen toegang tot deze school'}), 403
    user = User.query.filter_by(id=user_id, school_id=school_id).first_or_404()
    data = request.get_json() or {}
    role = data.get('role', '')
    allowed = ('teacher', 'director', 'school_ict')
    if current_user.role == 'school_ict' and role not in allowed:
        return jsonify({'error': f'Rol "{role}" mag niet worden toegewezen'}), 403
    if role not in VALID_ROLES:
        return jsonify({'error': f'Ongeldige rol: {role}'}), 400
    user.role = role
    db.session.commit()
    return jsonify({'user': user.to_dict()})


@admin_bp.route('/schools/<int:school_id>/users/<int:user_id>', methods=['DELETE'])
@login_required
@school_ict_required
def remove_user_from_school(school_id, user_id):
    if not current_user.is_scholengroep_ict and current_user.school_id != school_id:
        return jsonify({'error': 'Geen toegang tot deze school'}), 403
    user = User.query.filter_by(id=user_id, school_id=school_id).first_or_404()
    user.is_active = False
    audit_log('user.deactivate', 'user', target_type='user', target_id=str(user_id),
              detail={'email': user.email, 'role': user.role},
              school_id=current_user.school_id)
    db.session.commit()
    return jsonify({'deleted': True})


# ── Scholengroep ICT beheer (superadmin) ──────────────────────────────────────

@admin_bp.route('/scholengroep-ict', methods=['GET'])
@login_required
@superadmin_required
def list_scholengroep_ict():
    users = User.query.filter_by(role='scholengroep_ict', is_active=True)\
                      .order_by(User.last_name).all()
    return jsonify({'users': [u.to_dict() for u in users]})


@admin_bp.route('/scholengroep-ict', methods=['POST'])
@login_required
@superadmin_required
def add_scholengroep_ict():
    data  = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'E-mailadres is verplicht'}), 400

    user = User.query.filter_by(email=email).first()
    if user:
        user.role      = 'scholengroep_ict'
        user.school_id = None
        user.is_active = True
        db.session.commit()
        return jsonify({'user': user.to_dict()})

    user = User(
        email=email,
        first_name=data.get('first_name', '').strip(),
        last_name=data.get('last_name', '').strip(),
        role='scholengroep_ict',
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()
    audit_log('user.create', 'user', target_type='user', target_id=str(user.id),
              detail={'email': email, 'role': user.role, 'school_id': school_id},
              school_id=school_id)
    db.session.commit()
    return jsonify({'user': user.to_dict()}), 201


@admin_bp.route('/scholengroep-ict/<int:user_id>', methods=['DELETE'])
@login_required
@superadmin_required
def remove_scholengroep_ict(user_id):
    user = User.query.get_or_404(user_id)
    if user.role != 'scholengroep_ict':
        return jsonify({'error': 'Gebruiker is geen scholengroep ICT'}), 400
    user.is_active = False
    db.session.commit()
    return jsonify({'ok': True})


# ── Doelen upload (scholengroep_ict) ──────────────────────────────────────────

@admin_bp.route('/doelen', methods=['GET'])
@login_required
@scholengroep_ict_required
def list_doelen():
    from services.doelen import load_index, list_installed_vakken
    index     = load_index()
    installed = set(list_installed_vakken())
    return jsonify({
        'vakken':    index.get('vakken', []),
        'versie':    index.get('versie'),
        'installed': list(installed),
    })


@admin_bp.route('/doelen/upload', methods=['POST'])
@login_required
@scholengroep_ict_required
def upload_doelen():
    """
    Upload één of meerdere vak JSON bestanden via multipart/form-data (veld: 'files').
    Bij maandelijkse update gewoon opnieuw uploaden — overschrijft bestaande bestanden.
    """
    from services.doelen import validate_vak_json, save_vak, is_valid_vak_id

    if 'files' not in request.files:
        return jsonify({'error': 'Geen bestanden ontvangen (verwacht veld "files")'}), 400

    results = []

    for file in request.files.getlist('files'):
        if not file.filename:
            continue

        result = {'filename': file.filename, 'ok': False}

        if not file.filename.lower().endswith('.json'):
            result['error'] = 'Alleen .json bestanden zijn toegestaan'
            results.append(result)
            continue

        try:
            data = jsonlib.loads(file.read().decode('utf-8'))
        except Exception:
            result['error'] = 'Ongeldig JSON — kon bestand niet lezen'
            results.append(result)
            continue

        # Vak ID: uit het bestand zelf, anders van de bestandsnaam
        vak_id = (data.get('vak') or file.filename[:-5]).lower().strip()

        if not is_valid_vak_id(vak_id):
            result['error'] = f'Ongeldig vak ID: "{vak_id}"'
            results.append(result)
            continue

        errors = validate_vak_json(data)
        if errors:
            result['error'] = '; '.join(errors)
            results.append(result)
            continue

        doelzinnen = [r for r in data['rijen'] if r.get('type') == 'doelzin']
        save_vak(vak_id, data)

        result.update({
            'ok':               True,
            'vak_id':           vak_id,
            'vak_naam':         data.get('vakNaam') or vak_id,
            'aantalDoelzinnen': len(doelzinnen),
            'versie':           data.get('versie', '?'),
        })
        results.append(result)

    ok_count  = sum(1 for r in results if r['ok'])
    err_count = len(results) - ok_count

    return jsonify({
        'ok':      ok_count,
        'errors':  err_count,
        'results': results,
    }), (200 if ok_count > 0 else 400)


@admin_bp.route('/doelen/<vak_id>', methods=['DELETE'])
@login_required
@scholengroep_ict_required
def delete_doelen(vak_id):
    from services.doelen import delete_vak, is_valid_vak_id
    if not is_valid_vak_id(vak_id):
        return jsonify({'error': 'Ongeldig vak ID'}), 400
    if not delete_vak(vak_id):
        return jsonify({'error': 'Bestand niet gevonden'}), 404
    return jsonify({'deleted': True, 'vak_id': vak_id})


# ── Globale statistieken (superadmin) ─────────────────────────────────────────

@admin_bp.route('/stats')
@login_required
@scholengroep_ict_required
def global_stats():
    return jsonify({
        'schools':          School.query.count(),
        'users':            User.query.filter_by(is_active=True).count(),
        'teachers':         User.query.filter_by(role='teacher',         is_active=True).count(),
        'directors':        User.query.filter_by(role='director',        is_active=True).count(),
        'school_ict':       User.query.filter_by(role='school_ict',      is_active=True).count(),
        'scholengroep_ict': User.query.filter_by(role='scholengroep_ict',is_active=True).count(),
    })


# ── Klassen ───────────────────────────────────────────────────────────────────

@admin_bp.route('/schools/<int:school_id>/classes', methods=['GET'])
@login_required
@school_ict_required
def list_classes(school_id):
    if not current_user.is_scholengroep_ict and current_user.school_id != school_id:
        return jsonify({'error': 'Geen toegang'}), 403
    classes = Class.query.filter_by(school_id=school_id)                         .order_by(Class.name).all()
    return jsonify({'classes': [c.to_dict() for c in classes]})


@admin_bp.route('/schools/<int:school_id>/classes', methods=['POST'])
@login_required
@school_ict_required
def create_class(school_id):
    if not current_user.is_scholengroep_ict and current_user.school_id != school_id:
        return jsonify({'error': 'Geen toegang'}), 403
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Naam is verplicht'}), 400
    if Class.query.filter_by(school_id=school_id, name=name).first():
        return jsonify({'error': f'Klas "{name}" bestaat al'}), 409

    klas = Class(school_id=school_id, name=name)
    db.session.add(klas)
    db.session.flush()
    audit_log('class.create', 'class', target_type='class', target_id=str(klas.id),
              detail={'name': name}, school_id=school_id)
    db.session.commit()
    return jsonify({'class': klas.to_dict()}), 201


@admin_bp.route('/schools/<int:school_id>/classes/<int:class_id>', methods=['DELETE'])
@login_required
@school_ict_required
def delete_class(school_id, class_id):
    if not current_user.is_scholengroep_ict and current_user.school_id != school_id:
        return jsonify({'error': 'Geen toegang'}), 403
    klas = Class.query.filter_by(id=class_id, school_id=school_id).first_or_404()
    audit_log('class.delete', 'class', target_type='class', target_id=str(class_id),
              detail={'name': klas.name}, school_id=school_id)
    db.session.delete(klas)
    db.session.commit()
    return jsonify({'deleted': True})


@admin_bp.route('/schools/<int:school_id>/classes/<int:class_id>/teachers', methods=['PUT'])
@login_required
@school_ict_required
def set_class_teachers(school_id, class_id):
    """Vervang alle leerkrachten van een klas in één keer."""
    if not current_user.is_scholengroep_ict and current_user.school_id != school_id:
        return jsonify({'error': 'Geen toegang'}), 403
    klas      = Class.query.filter_by(id=class_id, school_id=school_id).first_or_404()
    data      = request.get_json() or {}
    user_ids  = data.get('user_ids', [])

    teachers = User.query.filter(
        User.id.in_(user_ids),
        User.school_id == school_id,
        User.is_active == True
    ).all()

    klas.teachers = teachers
    audit_log('class.teachers_updated', 'class', target_type='class', target_id=str(class_id),
              detail={'name': klas.name, 'teacher_ids': user_ids}, school_id=school_id)
    db.session.commit()
    return jsonify({'class': klas.to_dict()})


@admin_bp.route('/users/<int:user_id>/classes', methods=['GET'])
@login_required
def get_user_classes(user_id):
    """Geeft klassen terug van een specifieke leerkracht (voor leerkracht zelf of beheerder)."""
    if current_user.id != user_id and not current_user.is_school_ict:
        return jsonify({'error': 'Geen toegang'}), 403
    user    = User.query.get_or_404(user_id)
    classes = Class.query.filter_by(school_id=user.school_id)                         .order_by(Class.name).all()
    return jsonify({
        'all_classes':  [{'id': c.id, 'name': c.name} for c in classes],
        'my_classes':   [{'id': c.id, 'name': c.name} for c in user.classes],
    })


@admin_bp.route('/users/<int:user_id>/classes', methods=['PUT'])
@login_required
def set_user_classes(user_id):
    """Leerkracht stelt eigen klassen in, of beheerder doet het."""
    if current_user.id != user_id and not current_user.is_school_ict:
        return jsonify({'error': 'Geen toegang'}), 403
    user     = User.query.get_or_404(user_id)
    data     = request.get_json() or {}
    class_ids = data.get('class_ids', [])

    classes = Class.query.filter(
        Class.id.in_(class_ids),
        Class.school_id == user.school_id
    ).all()

    user.classes = classes
    audit_log('class.user_assignment', 'class', target_type='user', target_id=str(user_id),
              detail={'class_ids': class_ids, 'class_names': [c.name for c in classes]},
              school_id=user.school_id)
    db.session.commit()
    return jsonify({'classes': [{'id': c.id, 'name': c.name} for c in user.classes]})

