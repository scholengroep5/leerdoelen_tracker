from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


class School(db.Model):
    __tablename__ = 'schools'

    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(255), nullable=False)
    slug           = db.Column(db.String(100), nullable=False, unique=True)
    email_domains  = db.Column(db.ARRAY(db.Text), nullable=False, default=list)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    users        = db.relationship('User', back_populates='school', lazy='dynamic')
    school_years = db.relationship('SchoolYear', back_populates='school', lazy='dynamic')
    classes      = db.relationship('Class', back_populates='school', lazy='dynamic')

    def to_dict(self):
        return {
            'id':            self.id,
            'name':          self.name,
            'slug':          self.slug,
            'email_domains': self.email_domains or [],
        }


class SchoolYear(db.Model):
    __tablename__ = 'school_years'

    id         = db.Column(db.Integer, primary_key=True)
    # school_id=None = globaal schooljaar voor alle scholen
    school_id  = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='CASCADE'), nullable=True)
    label      = db.Column(db.String(20), nullable=False, unique=True)
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    school      = db.relationship('School', back_populates='school_years')
    assessments = db.relationship('Assessment', back_populates='school_year', lazy='dynamic')

    def to_dict(self):
        return {'id': self.id, 'label': self.label, 'is_active': self.is_active}


class Class(db.Model):
    __tablename__ = 'classes'

    id        = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='CASCADE'), nullable=False)
    name      = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    school   = db.relationship('School', back_populates='classes')
    teachers = db.relationship('User', secondary='teacher_classes', back_populates='classes')

    __table_args__ = (
        db.UniqueConstraint('school_id', 'name', name='uq_class_school_name'),
    )

    def to_dict(self):
        return {
            'id':       self.id,
            'name':     self.name,
            'school_id': self.school_id,
            'teachers': [{'id': t.id, 'full_name': t.full_name} for t in self.teachers],
        }


class TeacherClass(db.Model):
    __tablename__ = 'teacher_classes'

    user_id  = db.Column(db.Integer, db.ForeignKey('users.id',    ondelete='CASCADE'), primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id',  ondelete='CASCADE'), primary_key=True)


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id              = db.Column(db.Integer, primary_key=True)
    email           = db.Column(db.String(255), nullable=False, unique=True)
    password_hash   = db.Column(db.String(255))
    first_name      = db.Column(db.String(100))
    last_name       = db.Column(db.String(100))
    role            = db.Column(db.String(20), nullable=False, default='teacher')
    school_id       = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='SET NULL'))
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    last_login      = db.Column(db.DateTime)
    oauth_provider  = db.Column(db.String(20))
    oauth_id        = db.Column(db.String(255))
    entra_tenant_id = db.Column(db.String(255))

    school  = db.relationship('School', back_populates='users')
    classes = db.relationship('Class', secondary='teacher_classes', back_populates='teachers')

    @property
    def is_superadmin(self):      return self.role == 'superadmin'
    @property
    def is_scholengroep_ict(self): return self.role in ('superadmin', 'scholengroep_ict')
    @property
    def is_school_ict(self):      return self.role in ('superadmin', 'scholengroep_ict', 'school_ict')
    @property
    def is_director(self):        return self.role in ('superadmin', 'scholengroep_ict', 'school_ict', 'director')
    @property
    def is_teacher(self):         return self.role == 'teacher'

    def set_password(self, password):
        # scrypt is het sterkste algoritme in werkzeug — veel meer weerstand tegen brute force
        self.password_hash = generate_password_hash(password, method='scrypt')

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.email

    @property
    def class_names(self):
        return [c.name for c in self.classes]

    def to_dict(self):
        return {
            'id':          self.id,
            'email':       self.email,
            'first_name':  self.first_name,
            'last_name':   self.last_name,
            'full_name':   self.full_name,
            'role':        self.role,
            'school_id':   self.school_id,
            'school_name': self.school.name if self.school else None,
            'school':      self.school.to_dict() if self.school else None,
            'last_login':  self.last_login.isoformat() if self.last_login else None,
            'created_at':  self.created_at.isoformat() if self.created_at else None,
            'classes':     [{'id': c.id, 'name': c.name} for c in self.classes],
        }


class Assessment(db.Model):
    __tablename__ = 'assessments'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id',        ondelete='CASCADE'), nullable=False)
    school_id      = db.Column(db.Integer, db.ForeignKey('schools.id',      ondelete='CASCADE'), nullable=False)
    school_year_id = db.Column(db.Integer, db.ForeignKey('school_years.id', ondelete='CASCADE'), nullable=False)
    vak_id         = db.Column(db.String(50), nullable=False)
    goal_id        = db.Column(db.String(50), nullable=False)
    status         = db.Column(db.String(10), nullable=False)
    opmerking      = db.Column(db.String(500), nullable=True)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user        = db.relationship('User')
    school      = db.relationship('School')
    school_year = db.relationship('SchoolYear', back_populates='assessments')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'school_year_id', 'vak_id', 'goal_id'),
    )

    def to_dict(self):
        return {
            'id':         self.id,
            'vak_id':     self.vak_id,
            'goal_id':    self.goal_id,
            'status':     self.status,
            'opmerking':  self.opmerking,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id         = db.Column(db.Integer, primary_key=True)
    timestamp  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    school_id  = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='SET NULL'), nullable=True)
    action     = db.Column(db.String(50), nullable=False, index=True)
    # categorie: auth | user | school | class | assessment | doelen | system
    category   = db.Column(db.String(20), nullable=False, index=True)
    target_type = db.Column(db.String(50))   # bv. 'user', 'school', 'class'
    target_id   = db.Column(db.String(100))  # id of naam van het object
    detail      = db.Column(db.Text)         # extra context in JSON string
    ip_address  = db.Column(db.String(45))   # IPv4 of IPv6

    user   = db.relationship('User',   foreign_keys=[user_id])
    school = db.relationship('School', foreign_keys=[school_id])

    def to_dict(self):
        return {
            'id':          self.id,
            'timestamp':   self.timestamp.isoformat(),
            'user_id':     self.user_id,
            'user_name':   self.user.full_name if self.user else 'Systeem',
            'user_email':  self.user.email     if self.user else None,
            'school_id':   self.school_id,
            'school_name': self.school.name    if self.school else None,
            'action':      self.action,
            'category':    self.category,
            'target_type': self.target_type,
            'target_id':   self.target_id,
            'detail':      self.detail,
            'ip_address':  self.ip_address,
        }
