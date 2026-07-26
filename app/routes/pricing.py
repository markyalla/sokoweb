from flask import Blueprint, render_template, g, redirect, url_for, request, flash
from app.routes.models import HolidayPricingSetting
from app import db

pricing_bp = Blueprint('pricing', __name__)

# Ghana's fixed-date public holidays — shown read-only on the settings page
# so superadmin knows exactly when the surcharge kicks in. Mirrors the list
# used by the Go backend (internal/pricing/holiday.go) and the analytics
# dashboard (app/routes/analytics.py) — keep all three in sync if this changes.
GHANA_HOLIDAYS = [
    "New Year's Day (Jan 1)", "Independence Day (Mar 6)", "Labour Day (May 1)",
    "Republic Day (Jul 1)", "Founders' Day (Aug 4)",
    "Kwame Nkrumah Memorial Day (Sep 21)", "Christmas Day (Dec 25)", "Boxing Day (Dec 26)",
]


def _require_superadmin():
    if not g.user:
        return redirect(url_for('auth.login'))
    if 'superadmin' not in [r.role for r in g.user.roles]:
        flash('You do not have access to that section.', 'danger')
        return redirect(url_for('dashboard.index'))
    return None


@pricing_bp.route('/holiday')
def holiday_pricing():
    redir = _require_superadmin()
    if redir:
        return redir

    setting = HolidayPricingSetting.query.filter_by(country_code='GH').first()
    if not setting:
        setting = HolidayPricingSetting(
            country_code='GH', country_name='Ghana', surcharge_pct=15, enabled=False)
        db.session.add(setting)
        db.session.commit()

    return render_template('superadmin/holiday_pricing.html',
                           setting=setting, holidays=GHANA_HOLIDAYS)


@pricing_bp.route('/holiday/update', methods=['POST'])
def update_holiday_pricing():
    redir = _require_superadmin()
    if redir:
        return redir

    setting = HolidayPricingSetting.query.filter_by(country_code='GH').first()
    if not setting:
        flash('Setting not found.', 'danger')
        return redirect(url_for('pricing.holiday_pricing'))

    pct = request.form.get('surcharge_pct', '').strip()
    try:
        pct_val = float(pct)
    except ValueError:
        flash('Enter a valid surcharge percentage.', 'danger')
        return redirect(url_for('pricing.holiday_pricing'))

    if not (0 <= pct_val <= 100):
        flash('Surcharge must be between 0 and 100 percent.', 'danger')
        return redirect(url_for('pricing.holiday_pricing'))

    setting.surcharge_pct = pct_val
    setting.enabled = request.form.get('enabled') == 'on'
    db.session.commit()

    flash(f'Ghana holiday pricing {"enabled" if setting.enabled else "disabled"} '
          f'at {pct_val:.0f}% surcharge.', 'success')
    return redirect(url_for('pricing.holiday_pricing'))
