"""Enterprise ATT&CK from MITRE's TAXII 2.1 server, and how CMT lines up with it.

The website https://attack.mitre.org/ is the human view. The machine-readable
feed is the official TAXII API at https://attack-taxii.mitre.org/api/v21/.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app import db
from app.models.attack import AttackSync, AttackTactic, AttackTechnique

bp = Blueprint('attack', __name__, url_prefix='/administration/attack')

TAXII_ROOT = 'https://attack-taxii.mitre.org/api/v21/'
ENTERPRISE_COLLECTION = 'x-mitre-collection--1f5f1533-f617-4ca8-9ab4-6a02367fa019'
_ACCEPT = 'application/taxii+json;version=2.1'
# Small pages from this server overlap and skip techniques. One large page
# returns the whole Enterprise set (about 850 techniques today).
_PAGE_LIMIT = 2000
_MAX_PAGES = 30
_DESCRIPTION_LIMIT = 4000


class AttackSyncError(Exception):
    """The ATT&CK feed could not be read. Stored rows are left as they were."""


def taxii_get(url, timeout=90):
    request_headers = urllib.request.Request(
        url,
        headers={'Accept': _ACCEPT, 'User-Agent': 'CMT-attack-sync'},
    )
    try:
        with urllib.request.urlopen(request_headers, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise AttackSyncError(f'MITRE ATT&CK returned HTTP {exc.code}.') from exc
    except urllib.error.URLError as exc:
        raise AttackSyncError('Could not reach the MITRE ATT&CK server.') from exc
    except TimeoutError as exc:
        raise AttackSyncError('The MITRE ATT&CK server took too long to answer.') from exc
    except json.JSONDecodeError as exc:
        raise AttackSyncError('MITRE ATT&CK returned data that was not JSON.') from exc


def _objects_url(match_type, cursor=None):
    query = {'match[type]': match_type, 'limit': _PAGE_LIMIT}
    if cursor is not None:
        query['next'] = cursor
    return (
        f'{TAXII_ROOT}collections/{ENTERPRISE_COLLECTION}/objects/?'
        + urllib.parse.urlencode(query)
    )


def iter_objects(match_type, get):
    cursor = None
    for _page in range(_MAX_PAGES):
        payload = get(_objects_url(match_type, cursor))
        if not isinstance(payload, dict):
            raise AttackSyncError('MITRE ATT&CK returned an unexpected response.')
        for obj in payload.get('objects') or []:
            yield obj
        if not payload.get('more'):
            return
        cursor = payload.get('next')
        if cursor is None:
            return
    raise AttackSyncError('ATT&CK returned more pages than this sync will follow.')


def _attack_reference(obj):
    for ref in obj.get('external_references') or []:
        if ref.get('source_name') == 'mitre-attack' and ref.get('external_id'):
            return ref.get('external_id'), ref.get('url')
    return None, None


def _clip(value):
    text = (value or '').strip()
    if len(text) <= _DESCRIPTION_LIMIT:
        return text
    return text[:_DESCRIPTION_LIMIT].rstrip() + '…'


def fetch_matrix(get):
    """Download tactics, techniques, and the Enterprise ATT&CK version."""
    collection = get(_objects_url('x-mitre-collection'))
    objects = collection.get('objects') if isinstance(collection, dict) else None
    if not objects:
        raise AttackSyncError('MITRE did not return the Enterprise ATT&CK collection.')
    header = objects[0]
    tactics = []
    for obj in iter_objects('x-mitre-tactic', get):
        external_id, url = _attack_reference(obj)
        if not external_id or not obj.get('id') or not obj.get('name'):
            continue
        tactics.append({
            'stix_id': obj['id'],
            'external_id': external_id,
            'name': obj['name'][:120],
            'shortname': (obj.get('x_mitre_shortname') or '')[:80],
            'url': url,
            'modified': obj.get('modified'),
        })
    techniques = []
    for obj in iter_objects('attack-pattern', get):
        external_id, url = _attack_reference(obj)
        if not external_id or not obj.get('id') or not obj.get('name'):
            continue
        phases = [
            phase.get('phase_name')
            for phase in obj.get('kill_chain_phases') or []
            if phase.get('phase_name')
        ]
        techniques.append({
            'stix_id': obj['id'],
            'external_id': external_id[:16],
            'name': obj['name'][:240],
            'description': _clip(obj.get('description')),
            'url': url,
            'tactics': ','.join(phases)[:500],
            'modified': obj.get('modified'),
            'version': (obj.get('x_mitre_version') or '')[:20],
            'revoked': bool(obj.get('revoked')),
            'deprecated': bool(obj.get('x_mitre_deprecated')),
            'is_subtechnique': bool(obj.get('x_mitre_is_subtechnique')),
        })
    if not techniques:
        raise AttackSyncError('MITRE did not return any Enterprise techniques.')
    # The feed can repeat a STIX id. Keep the current, non-revoked copy.
    return {
        'attack_version': str(header.get('x_mitre_version') or ''),
        'matrix_modified': header.get('modified'),
        'tactics': _dedupe(tactics),
        'techniques': _dedupe(techniques),
    }


def _dedupe(rows):
    chosen = {}
    for row in rows:
        current = chosen.get(row['stix_id'])
        if current is None:
            chosen[row['stix_id']] = row
            continue
        current_revoked = bool(current.get('revoked'))
        candidate_revoked = bool(row.get('revoked'))
        if current_revoked and not candidate_revoked:
            chosen[row['stix_id']] = row
            continue
        if candidate_revoked and not current_revoked:
            continue
        if (row.get('modified') or '') >= (current.get('modified') or ''):
            chosen[row['stix_id']] = row
    return list(chosen.values())


def sync_enterprise_attack(get=taxii_get):
    """Replace the local matrix only after a complete download."""
    matrix = fetch_matrix(get)
    try:
        _store_matrix(matrix)
    except Exception:
        db.session.rollback()
        raise
    return db.session.get(AttackSync, 1)


def _store_matrix(matrix):
    db.session.query(AttackTactic).delete(synchronize_session=False)
    db.session.query(AttackTechnique).delete(synchronize_session=False)
    for row in matrix['tactics']:
        db.session.add(AttackTactic(**row))
    for row in matrix['techniques']:
        db.session.add(AttackTechnique(**row))
    state = db.session.get(AttackSync, 1)
    if state is None:
        state = AttackSync(id=1)
        db.session.add(state)
    state.attack_version = matrix['attack_version']
    state.matrix_modified = matrix['matrix_modified']
    state.synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
    state.technique_count = len(matrix['techniques'])
    state.tactic_count = len(matrix['tactics'])
    state.source_url = TAXII_ROOT
    db.session.commit()


def technique_url(external_id, official=None):
    if official:
        return official
    if '.' in external_id:
        parent, sub = external_id.split('.', 1)
        return f'https://attack.mitre.org/techniques/{parent}/{sub}'
    return f'https://attack.mitre.org/techniques/{external_id}'


def _current_technique(external_id):
    rows = AttackTechnique.query.filter_by(external_id=external_id).all()
    for row in rows:
        if not row.revoked and not row.deprecated:
            return row
    return rows[0] if rows else None


def _env_flag(name):
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes')


def coverage_rows():
    """Techniques that apply to this web app, judged from what the code actually does."""
    secure_cookie = bool(current_app.config.get('SESSION_COOKIE_SECURE'))
    default_secret = current_app.config.get('SECRET_KEY') == 'dev-secret-change-me'
    demo_seed_disabled = _env_flag('CMT_DISABLE_DEMO_SEED')
    rows = [
        {
            'technique_id': 'T1110',
            'status': 'in_place',
            'control': 'Login rate limit and account lockout',
            'summary': 'Each IP address gets 30 login attempts a minute. Repeated failures lock that account for longer each time.',
        },
        {
            'technique_id': 'T1110.001',
            'status': 'in_place',
            'control': 'Slow password hashing and a 12-character minimum',
            'summary': 'Passwords use scrypt with N=131072, r=8, p=1. New and changed passwords must be at least 12 characters. Existing shorter passwords still sign in and are re-hashed.',
        },
        {
            'technique_id': 'T1110.003',
            'status': 'partial',
            'control': 'Per-account lockout only',
            'summary': 'One account locks after repeated failures. The same password tried across many accounts is only slowed by the per-IP limit.',
        },
        {
            'technique_id': 'T1078',
            'status': 'partial',
            'control': 'Authenticator app for super admins',
            'summary': 'A super admin must confirm a 6-digit code or a one-time recovery code. Other accounts still sign in with a password only.',
        },
        {
            'technique_id': 'T1078.001',
            'status': 'partial' if demo_seed_disabled else 'gap',
            'control': 'Demo account on an empty database',
            'summary': (
                'Demo seeding is off because CMT_DISABLE_DEMO_SEED is set. Delete any admin / admin123 account that was created earlier.'
                if demo_seed_disabled else
                'An empty database creates admin / admin123 so the app can be tried locally. Set CMT_DISABLE_DEMO_SEED=1 before a production database is created, and do not keep that password.'
            ),
        },
        {
            'technique_id': 'T1552.001',
            'status': 'partial' if default_secret else 'in_place',
            'control': 'Hashed passwords and a secret outside the database',
            'summary': (
                'Passwords and recovery codes are scrypt hashes, not plaintext. SECRET_KEY is still the built-in development value. Set a long random SECRET_KEY in the environment.'
                if default_secret else
                'Passwords and recovery codes are scrypt hashes. SECRET_KEY comes from the environment, so it is not the built-in development value.'
            ),
        },
        {
            'technique_id': 'T1606',
            'status': 'partial' if default_secret else 'in_place',
            'control': 'Signed session cookies',
            'summary': (
                'Session cookies are signed with SECRET_KEY. That key is still the development default, so anyone who knows it can forge a session.'
                if default_secret else
                'Session cookies are signed with the environment SECRET_KEY.'
            ),
        },
        {
            'technique_id': 'T1539',
            'status': 'in_place' if secure_cookie else 'partial',
            'control': 'Session cookie flags',
            'summary': (
                'Session and remember-me cookies are HttpOnly, SameSite=Lax, and Secure.'
                if secure_cookie else
                'Session and remember-me cookies are HttpOnly and SameSite=Lax. Set SESSION_COOKIE_SECURE=1 when the site is served over HTTPS so the browser will not send them on plain HTTP.'
            ),
        },
        {
            'technique_id': 'T1040',
            'status': 'partial' if secure_cookie else 'gap',
            'control': 'HTTPS in front of the app',
            'summary': 'CMT does not terminate TLS. Put it behind HTTPS. SESSION_COOKIE_SECURE is '
            + ('on.' if secure_cookie else 'off, so cookies can still be sent over plain HTTP.'),
        },
        {
            'technique_id': 'T1190',
            'status': 'partial',
            'control': 'CSRF checks and signed webhooks',
            'summary': 'State-changing forms use CSRF tokens. The Stripe webhook rejects a bad signature and does not grant access from the browser return page. This does not mean every future bug is closed.',
        },
        {
            'technique_id': 'T1111',
            'status': 'gap',
            'control': 'Phishing-resistant admin sign-in',
            'summary': 'Admin MFA is a time-based code. That code can be phished. A hardware key or passkey is not built in yet.',
        },
    ]
    order = {'gap': 0, 'partial': 1, 'in_place': 2}
    rows.sort(key=lambda row: (order[row['status']], row['technique_id']))
    for row in rows:
        stored = _current_technique(row['technique_id'])
        row['official_name'] = stored.name if stored else None
        row['modified'] = stored.modified if stored else None
        row['revoked'] = bool(stored and (stored.revoked or stored.deprecated))
        row['url'] = technique_url(row['technique_id'], stored.url if stored else None)
    return rows


def _require_super_admin():
    if not current_user.is_super_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
    return None


@bp.route('/')
@login_required
def matrix():
    denied = _require_super_admin()
    if denied is not None:
        return denied
    query_text = (request.args.get('q') or '').strip()[:80]
    page = request.args.get('page', '1')
    try:
        page = max(int(page), 1)
    except ValueError:
        page = 1
    techniques = AttackTechnique.query
    if query_text:
        safe = query_text.replace('%', '').replace('_', '')
        like = f'%{safe}%'
        techniques = techniques.filter(or_(
            AttackTechnique.external_id.ilike(like),
            AttackTechnique.name.ilike(like),
        ))
    techniques = techniques.order_by(AttackTechnique.external_id)
    page_size = 40
    total = techniques.count()
    rows = techniques.offset((page - 1) * page_size).limit(page_size).all()
    pages = max((total + page_size - 1) // page_size, 1)
    covered = coverage_rows()
    counts = {'gap': 0, 'partial': 0, 'in_place': 0}
    for row in covered:
        counts[row['status']] += 1
    return render_template(
        'administration/attack.html',
        sync=db.session.get(AttackSync, 1),
        covered=covered,
        counts=counts,
        techniques=rows,
        query_text=query_text,
        page=page,
        pages=pages,
        total=total,
        source_url=TAXII_ROOT,
    )


@bp.route('/sync', methods=['POST'])
@login_required
def sync():
    denied = _require_super_admin()
    if denied is not None:
        return denied
    try:
        state = sync_enterprise_attack(taxii_get)
    except AttackSyncError as exc:
        current_app.logger.warning('ATT&CK sync failed: %s', exc)
        flash(str(exc), 'danger')
        return redirect(url_for('attack.matrix'))
    flash(
        f'Enterprise ATT&CK {state.attack_version} is saved '
        f'({state.technique_count} techniques, {state.tactic_count} tactics).',
        'success',
    )
    return redirect(url_for('attack.matrix'))
