"""Local copy of Enterprise ATT&CK, refreshed from MITRE's TAXII server."""

from app import db


class AttackTechnique(db.Model):
    __tablename__ = 'attack_technique'
    stix_id = db.Column(db.String(80), primary_key=True)
    external_id = db.Column(db.String(16), index=True, nullable=False)
    name = db.Column(db.String(240), nullable=False)
    description = db.Column(db.Text)
    url = db.Column(db.String(300))
    tactics = db.Column(db.Text)
    modified = db.Column(db.String(40))
    version = db.Column(db.String(20))
    revoked = db.Column(db.Boolean, default=False)
    deprecated = db.Column(db.Boolean, default=False)
    is_subtechnique = db.Column(db.Boolean, default=False)

    @property
    def tactic_names(self):
        if not self.tactics:
            return []
        return [name for name in self.tactics.split(',') if name]


class AttackTactic(db.Model):
    __tablename__ = 'attack_tactic'
    stix_id = db.Column(db.String(80), primary_key=True)
    external_id = db.Column(db.String(16), index=True)
    name = db.Column(db.String(120), nullable=False)
    shortname = db.Column(db.String(80))
    url = db.Column(db.String(300))
    modified = db.Column(db.String(40))


class AttackSync(db.Model):
    __tablename__ = 'attack_sync'
    id = db.Column(db.Integer, primary_key=True)
    attack_version = db.Column(db.String(20))
    matrix_modified = db.Column(db.String(40))
    synced_at = db.Column(db.DateTime)
    technique_count = db.Column(db.Integer, default=0)
    tactic_count = db.Column(db.Integer, default=0)
    source_url = db.Column(db.String(200))
