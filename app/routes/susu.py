from flask import Blueprint, flash, g, redirect, render_template, request, url_for
import requests
from flask import current_app
from app.routes.models import SusuContribution, SusuGroup, SusuMember, SusuPayout

susu_bp = Blueprint('susu', __name__)


def _require_role():
    if not g.user:
        return redirect(url_for('auth.login'))
    roles = [r.role for r in g.user.roles]
    if 'superadmin' not in roles and 'sokosusu_admin' not in roles:
        flash('You do not have access to that section.', 'danger')
        return redirect(url_for('dashboard.index'))


def _api_headers():
    from flask import session
    token = session.get('backend_token', '')
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def _api_base():
    return current_app.config.get('API_BASE_URL', 'http://localhost:8082').rstrip('/')


@susu_bp.route('/')
def index():
    redir = _require_role()
    if redir:
        return redir
    groups = SusuGroup.query.order_by(SusuGroup.created_at.desc()).all()
    stats = {
        'total': len(groups),
        'forming': sum(1 for g_ in groups if g_.status == 'forming'),
        'active': sum(1 for g_ in groups if g_.status == 'active'),
        'completed': sum(1 for g_ in groups if g_.status == 'completed'),
    }
    return render_template('susu/groups.html', groups=groups, stats=stats)


@susu_bp.route('/groups/create', methods=['GET', 'POST'])
def create_group():
    redir = _require_role()
    if redir:
        return redir

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        amount = request.form.get('contribution_amount', '')
        cycle_period = request.form.get('cycle_period', 'monthly')
        max_members = request.form.get('max_members', '')

        if not name or not amount or not max_members:
            flash('All fields are required.', 'danger')
            return render_template('susu/create_group.html')

        try:
            payload = {
                'name': name,
                'contribution_amount': float(amount),
                'cycle_period': cycle_period,
                'max_members': int(max_members),
            }
            resp = requests.post(
                f'{_api_base()}/api/v1/susu/groups',
                json=payload,
                headers=_api_headers(),
                timeout=10,
            )
            if resp.status_code == 201:
                flash(f'Group "{name}" created successfully.', 'success')
                return redirect(url_for('susu.index'))
            else:
                error = resp.json().get('error', 'Unknown error')
                flash(f'Failed to create group: {error}', 'danger')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')

    return render_template('susu/create_group.html')


@susu_bp.route('/groups/<group_id>')
def group_detail(group_id):
    redir = _require_role()
    if redir:
        return redir

    from app.routes.models import User

    group = SusuGroup.query.get_or_404(group_id)
    members = SusuMember.query.filter_by(group_id=group_id).order_by(SusuMember.position).all()

    # Cross-database: fetch User records for all members in one query
    user_ids = [m.user_id for m in members]
    user_map = {}
    if user_ids:
        users = User.query.filter(User.id.in_(user_ids)).all()
        user_map = {str(u.id): u for u in users}

    contributions = (
        SusuContribution.query
        .filter_by(group_id=group_id)
        .order_by(SusuContribution.cycle_number, SusuContribution.created_at)
        .all()
    )
    payouts = (
        SusuPayout.query
        .filter_by(group_id=group_id)
        .order_by(SusuPayout.cycle_number)
        .all()
    )

    cycle_summary = {}
    for c in contributions:
        cycle_summary.setdefault(c.cycle_number, 0)
        cycle_summary[c.cycle_number] += 1

    # Who has contributed in the latest cycle
    current_cycle = max((c.cycle_number for c in contributions), default=1)
    contributed_this_cycle = {
        str(c.user_id) for c in contributions if c.cycle_number == current_cycle
    }

    return render_template(
        'susu/group_detail.html',
        group=group,
        members=members,
        user_map=user_map,
        contributions=contributions,
        payouts=payouts,
        cycle_summary=cycle_summary,
        current_cycle=current_cycle,
        contributed_this_cycle=contributed_this_cycle,
    )


@susu_bp.route('/groups/<group_id>/activate', methods=['POST'])
def activate_group(group_id):
    redir = _require_role()
    if redir:
        return redir
    group = SusuGroup.query.get_or_404(group_id)
    group.status = 'active'
    from app import db
    db.session.commit()
    flash(f'Group "{group.name}" is now active.', 'success')
    return redirect(url_for('susu.group_detail', group_id=group_id))


@susu_bp.route('/groups/<group_id>/complete', methods=['POST'])
def complete_group(group_id):
    redir = _require_role()
    if redir:
        return redir
    group = SusuGroup.query.get_or_404(group_id)
    group.status = 'completed'
    from app import db
    db.session.commit()
    flash(f'Group "{group.name}" marked as completed.', 'success')
    return redirect(url_for('susu.group_detail', group_id=group_id))
