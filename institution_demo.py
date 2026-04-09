"""
Demo Institution Portal (e.g. National Bank)
=============================================
This simulates how a real institution (bank, telecom, hospital, etc.)
integrates with the FIG Gateway to authenticate citizens using their
digital credentials.

Flow:
1. Citizen visits the institution's portal
2. Citizen presents their FIG credential token (paste or QR scan)
3. Institution's backend calls FIG Gateway API to validate the token
4. If valid, citizen is authenticated and can access services
5. Institution can also request deeper verification (KYC, age, tax ID)
   which requires citizen consent through the FIG Citizen Portal

Run: python institution_demo.py
(Runs on port 5001 while the FIG Gateway runs on port 5002)
"""

import json
import os
from datetime import datetime, timedelta

import requests
from flask import Flask, render_template_string, request, redirect, session, flash, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('INSTITUTION_SECRET_KEY', 'demo-institution-secret-key')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


@app.before_request
def _make_session_permanent():
    session.permanent = True

# ─── Configuration ─────────────────────────────────────────
# In production, these come from the institution's config after
# registering with the FIG Gateway
FIG_GATEWAY_URL = os.environ.get('FIG_GATEWAY_URL', 'http://localhost:5002')
INSTITUTION_API_KEY = os.environ.get('INSTITUTION_API_KEY')  # Set via env var on Render

INSTITUTION_NAME = 'National Bank of Nigeria'
INSTITUTION_SECTOR = 'Banking & Financial Services'
# Identity category this institution requires for KYC. A hospital would set 'health'.
INSTITUTION_REQUIRED_CATEGORY = 'banking'

# ── Dummy citizen profiles (mirrors FNDIG gateway profiles) ──
_DEMO_PROFILES = {
    'NIN-2026-001': {
        'first_name': 'Peter', 'last_name': 'Ndujekwu', 'middle_name': 'Ugochukwu',
        'date_of_birth': '03 April 2003', 'gender': 'Male',
        'phone': '0803-123-4567', 'email': 'peter.ndujekwu@example.ng',
        'address': '1 Innovation Drive, Lekki, Lagos', 'state': 'Lagos State',
        'nationality': 'Nigerian', 'marital_status': 'Single', 'occupation': 'Software Developer',
        'nin': 'NIN-2026-001', 'bvn': 'BVN-22113344556',
        'tin': 'TIN-5566778', 'nhis': 'NHIS-PUN-9091',
        'vin': 'PVC-PUN001', 'rsa': None,
        'bank': 'GTBank (existing)', 'acct': '0123456789',
    },
}


def _get_demo_profile(national_id):
    p = _DEMO_PROFILES.get(national_id)
    if not p:
        p = {
            'first_name': 'Peter', 'last_name': 'Ndujekwu',
            'middle_name': 'Ugochukwu', 'date_of_birth': '03 April 2003', 'gender': 'Male',
            'phone': '0803-123-4567', 'email': 'peter.ndujekwu@example.ng',
            'address': '1 Innovation Drive, Lekki, Lagos', 'state': 'Lagos State',
            'nationality': 'Nigerian', 'marital_status': 'Single', 'occupation': 'Software Developer',
            'nin': national_id, 'bvn': 'BVN-22113344556',
            'tin': 'TIN-5566778', 'nhis': 'NHIS-PUN-9091',
            'vin': 'PVC-PUN001', 'rsa': None,
            'bank': None, 'acct': None,
        }
    return p


# ─── HTML Templates ────────────────────────────────────────

BASE_CSS = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Institution Portal</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
    :root {
        --primary:       #0f172a;
        --accent:        #ea580c;
        --accent-dark:   #c2410c;
        --success:       #059669;
        --success-bg:    #ecfdf5;
        --success-bdr:   #a7f3d0;
        --warning:       #d97706;
        --warning-bg:    #fffbeb;
        --warning-bdr:   #fcd34d;
        --danger:        #dc2626;
        --danger-bg:     #fef2f2;
        --danger-bdr:    #fca5a5;
        --info:          #0284c7;
        --info-bg:       #f0f9ff;
        --info-bdr:      #bae6fd;
        --bg:            #f8fafc;
        --surface:       #ffffff;
        --border:        #e2e8f0;
        --border-subtle: #f1f5f9;
        --text:          #0f172a;
        --text-muted:    #64748b;
        --text-subtle:   #94a3b8;
    }
    *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
    body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        background: var(--bg);
        color: var(--text);
        line-height: 1.6;
        font-size: 15px;
        -webkit-font-smoothing: antialiased;
    }

    /* ── Topbar ─────────────────────────────────────── */
    .topbar {
        background: var(--primary);
        color: white;
        padding: 0 2rem;
        height: 60px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        position: sticky;
        top: 0;
        z-index: 100;
        box-shadow: 0 1px 4px rgba(0,0,0,0.25);
    }
    .topbar-brand { display:flex; align-items:center; gap:0.75rem; }
    .topbar-icon {
        width: 34px; height: 34px;
        background: linear-gradient(135deg, #ea580c, #c2410c);
        border-radius: 8px;
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 2px 6px rgba(234,88,12,0.45);
    }
    .topbar-icon svg { width:18px; height:18px; color:white; }
    .topbar-name { font-size:0.925rem; font-weight:700; letter-spacing:-0.01em; }
    .topbar-meta { font-size:0.66rem; color:rgba(255,255,255,0.45); margin-top:1px; }
    .topbar-right { display:flex; align-items:center; gap:1rem; }
    .topbar-right a {
        color: rgba(255,255,255,0.55);
        text-decoration: none;
        font-size: 0.83rem;
        display: flex; align-items: center; gap:0.375rem;
        transition: color 0.15s;
    }
    .topbar-right a svg { width:14px; height:14px; }
    .topbar-right a:hover { color: white; }

    /* ── Layout ─────────────────────────────────────── */
    .container { max-width: 920px; margin: 0 auto; padding: 2rem 1.5rem; }
    .container-sm { max-width: 520px; margin: 0 auto; padding: 2rem 1.5rem; }

    /* ── Cards ──────────────────────────────────────── */
    .card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1.25rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .card-accent { border-color: var(--accent); border-width: 2px; }
    .card-success { border-color: var(--success); border-width: 2px; }
    .card-title {
        font-size: 0.9rem; font-weight: 600; color: var(--text);
        margin-bottom: 1rem; padding-bottom: 0.75rem;
        border-bottom: 1px solid var(--border-subtle);
    }

    /* ── Buttons ────────────────────────────────────── */
    .btn {
        display: inline-flex; align-items: center; gap:0.4rem;
        padding: 0.525rem 1rem;
        border: 1px solid transparent; border-radius: 7px;
        font-size: 0.855rem; font-weight: 500; cursor: pointer;
        text-decoration: none; font-family: inherit;
        transition: all 0.15s; line-height: 1.4; white-space: nowrap;
    }
    .btn-primary { background:var(--accent); color:white; box-shadow:0 1px 3px rgba(234,88,12,0.3); }
    .btn-primary:hover { background:var(--accent-dark); }
    .btn-outline { background:white; border-color:var(--border); color:var(--text); box-shadow:0 1px 2px rgba(0,0,0,0.04); }
    .btn-outline:hover { background:var(--bg); border-color:#cbd5e1; }
    .btn-success { background:var(--success); color:white; box-shadow:0 1px 3px rgba(5,150,105,0.3); }
    .btn-success:hover { background:#047857; }
    .btn-full { width:100%; justify-content:center; padding:0.65rem 1rem; font-size:0.9rem; }
    .btn-sm { padding:0.3rem 0.65rem; font-size:0.78rem; border-radius:5px; }

    /* ── Forms ──────────────────────────────────────── */
    .form-group { margin-bottom: 1rem; }
    .form-group label {
        display: block; font-size: 0.78rem; font-weight: 600;
        color: var(--text-muted); margin-bottom: 0.35rem; letter-spacing: 0.01em;
    }
    .form-group input,
    .form-group textarea,
    .form-group select {
        width: 100%; padding: 0.575rem 0.75rem;
        border: 1px solid var(--border); border-radius: 7px;
        font-size: 0.9rem; font-family: inherit; color: var(--text);
        background: white; transition: border-color 0.15s, box-shadow 0.15s;
        appearance: none;
    }
    .form-group textarea {
        font-family: 'Fira Code', 'Cascadia Code', monospace;
        font-size: 0.8rem; resize: vertical; min-height: 80px;
    }
    .form-group select {
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='%2364748b'%3E%3Cpath fill-rule='evenodd' d='M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 0.625rem center;
        background-size: 1rem;
        padding-right: 2.25rem;
    }
    .form-group input:focus,
    .form-group textarea:focus,
    .form-group select:focus {
        outline: none; border-color: var(--accent);
        box-shadow: 0 0 0 3px rgba(234,88,12,0.12);
    }
    .form-group input::placeholder,
    .form-group textarea::placeholder { color: var(--text-subtle); }
    .form-hint { font-size:0.73rem; color:var(--text-subtle); margin-top:0.3rem; }

    /* ── Alerts ─────────────────────────────────────── */
    .alert {
        padding: 0.75rem 1rem; border-radius: 8px;
        margin-bottom: 1rem; font-size: 0.875rem;
        border: 1px solid transparent; border-left-width: 3px;
    }
    .alert-success { background:var(--success-bg); color:#065f46; border-color:var(--success-bdr); border-left-color:var(--success); }
    .alert-error   { background:var(--danger-bg);  color:#991b1b; border-color:var(--danger-bdr);  border-left-color:var(--danger); }
    .alert-warning { background:var(--warning-bg); color:#92400e; border-color:var(--warning-bdr); border-left-color:var(--warning); }
    .alert-info    { background:var(--info-bg);    color:#075985; border-color:var(--info-bdr);    border-left-color:var(--info); }

    /* ── Badges ─────────────────────────────────────── */
    .badge {
        display: inline-flex; align-items: center;
        padding: 0.2rem 0.55rem; border-radius: 20px;
        font-size: 0.7rem; font-weight: 600; letter-spacing: 0.02em; white-space: nowrap;
    }
    .badge-success { background:var(--success-bg); color:#065f46; border:1px solid var(--success-bdr); }
    .badge-danger  { background:var(--danger-bg);  color:#991b1b; border:1px solid var(--danger-bdr); }
    .badge-warning { background:var(--warning-bg); color:#92400e; border:1px solid var(--warning-bdr); }
    .badge-info    { background:var(--info-bg);    color:#075985; border:1px solid var(--info-bdr); }
    .badge-neutral { background:#f1f5f9; color:#475569; border:1px solid #e2e8f0; }

    /* ── Tables ─────────────────────────────────────── */
    .table-wrap { overflow-x: auto; }
    table { width:100%; border-collapse:collapse; font-size:0.855rem; }
    th, td { padding:0.7rem 1rem; text-align:left; border-bottom:1px solid var(--border-subtle); }
    th { background:#f8fafc; font-size:0.72rem; font-weight:600; text-transform:uppercase; letter-spacing:0.07em; color:var(--text-subtle); }
    tbody tr:hover { background:#f8fbff; }
    tbody tr:last-child td { border-bottom: none; }

    /* ── Result box ─────────────────────────────────── */
    .result-box {
        background: #0f172a; color: #4ade80;
        font-family: 'Fira Code', monospace; font-size: 0.78rem;
        padding: 1rem; border-radius: 8px; white-space: pre-wrap;
        margin-top: 1rem; line-height: 1.65;
    }

    /* ── Flow steps ─────────────────────────────────── */
    .flow-steps {
        display: flex; align-items: flex-start;
        gap: 0; margin: 1.5rem 0;
    }
    .flow-step { flex:1; text-align:center; position:relative; padding: 0 0.5rem; }
    .flow-step::after {
        content: '';
        position: absolute; top: 18px; left: 50%; right: -50%;
        height: 2px; background: var(--border); z-index: 0;
    }
    .flow-step:last-child::after { display:none; }
    .flow-step.done::after { background: var(--success); }
    .step-bubble {
        display: inline-flex; align-items: center; justify-content: center;
        width: 36px; height: 36px; border-radius: 50%;
        border: 2px solid var(--border); background: white;
        font-size: 0.8rem; font-weight: 700; color: var(--text-subtle);
        position: relative; z-index: 1; transition: all 0.2s;
    }
    .flow-step.done .step-bubble  { background:var(--success); border-color:var(--success); color:white; }
    .flow-step.done .step-bubble::before { content:'✓'; }
    .flow-step.active .step-bubble { background:var(--accent); border-color:var(--accent); color:white; }
    .step-text { font-size:0.75rem; color:var(--text-subtle); margin-top:0.5rem; line-height:1.4; }
    .flow-step.done .step-text   { color:var(--success); font-weight:500; }
    .flow-step.active .step-text { color:var(--accent); font-weight:600; }

    /* ── Service grid ───────────────────────────────── */
    .service-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(168px,1fr)); gap:0.875rem; }
    .service-card {
        background: white; border: 1px solid var(--border);
        border-radius: 10px; padding: 1.125rem;
        transition: all 0.2s; cursor: default;
    }
    .service-card:hover { border-color:#cbd5e1; box-shadow:0 4px 12px rgba(0,0,0,0.07); transform:translateY(-1px); }
    .svc-icon {
        width: 36px; height: 36px; background: var(--success-bg);
        border-radius: 9px; display:flex; align-items:center; justify-content:center; margin-bottom:0.75rem;
    }
    .svc-icon svg { width:18px; height:18px; color:var(--success); }
    .service-card h4 { font-size:0.875rem; font-weight:600; color:var(--text); margin-bottom:0.2rem; }
    .service-card p { font-size:0.775rem; color:var(--text-muted); line-height:1.5; }

    /* ── Verified banner ────────────────────────────── */
    .verified-banner {
        background: linear-gradient(135deg, #064e3b 0%, #059669 100%);
        color: white; border-radius: 12px; padding: 1.5rem;
        margin-bottom: 1.25rem;
        display: flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:1rem;
    }
    .verified-banner h2 { font-size:1.1rem; font-weight:700; letter-spacing:-0.02em; margin-bottom:0.2rem; }
    .verified-banner p  { font-size:0.84rem; opacity:0.85; }
    .verified-chip {
        display: inline-flex; align-items:center; gap:0.4rem;
        background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.25);
        border-radius: 20px; padding: 0.35rem 0.875rem;
        font-size: 0.8rem; font-weight: 600; white-space: nowrap;
    }
    .verified-chip svg { width:13px; height:13px; }

    /* ── Info highlight box ─────────────────────────── */
    .info-box {
        background: var(--info-bg); border: 1px solid var(--info-bdr);
        border-radius: 8px; padding: 1.125rem 1.25rem; margin-bottom:1rem;
    }
    .info-box p { font-size:0.875rem; color:#075985; line-height:1.6; }
    .info-box strong { color:#0369a1; }

    /* ── Inner data table (verification results) ────── */
    .data-table { border:none; background:#f8fafc; border-radius:6px; overflow:hidden; }
    .data-table td { padding:0.3rem 0.625rem; border:none; font-size:0.8rem; }
    .data-table td:first-child { color:var(--text-muted); font-weight:600; width:120px; }

    /* ── Two-col form grid ──────────────────────────── */
    .grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:1rem; }
    .inline-row { display:flex; gap:1rem; align-items:flex-end; }
    .inline-row .form-group { flex:1; margin-bottom:0; }

    @media(max-width:640px) {
        .grid-2 { grid-template-columns:1fr; }
        .flow-steps { flex-direction:column; gap:0.75rem; }
        .flow-step::after { display:none; }
        .container { padding:1rem; }
        .inline-row { flex-direction:column; }
        .inline-row .form-group { margin-bottom:0; }
    }
    </style>
</head>
<body>
"""

# ─────────────────────────────────────────────────────────────
# Login / 3FA entry
# ─────────────────────────────────────────────────────────────
LOGIN_PAGE = BASE_CSS + """
<div class="topbar">
    <div class="topbar-brand">
        <div class="topbar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21h18M3 10h18M5 6l7-3 7 3M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/>
            </svg>
        </div>
        <div>
            <div class="topbar-name">{{ name }}</div>
            <div class="topbar-meta">{{ sector }} &middot; Powered by FNDIG</div>
        </div>
    </div>
</div>

<div class="container-sm" style="padding-top:3rem;">
    {% for cat, msg in messages %}
    <div class="alert alert-{{ cat }}">{{ msg }}</div>
    {% endfor %}

    <div style="text-align:center; margin-bottom:2rem;">
        <div style="width:52px;height:52px;background:linear-gradient(135deg,#ea580c,#c2410c);border-radius:14px;display:flex;align-items:center;justify-content:center;margin:0 auto 1rem;box-shadow:0 4px 14px rgba(234,88,12,0.35);">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
            </svg>
        </div>
        <h1 style="font-size:1.5rem;font-weight:800;color:var(--text);letter-spacing:-0.02em;margin-bottom:0.375rem;">Sign Up to {{ name }}</h1>
        <p style="font-size:0.875rem;color:var(--text-muted);line-height:1.6;">
            Enter your National Identification Number and portal password.<br>
            An OTP will be sent to your registered SIM to complete sign-in.
        </p>
    </div>

    <div class="flow-steps" style="margin-bottom:2rem;">
        <div class="flow-step active">
            <div class="step-bubble">1</div>
            <div class="step-text"><strong>NIN</strong><br>&amp; Password</div>
        </div>
        <div class="flow-step">
            <div class="step-bubble">2</div>
            <div class="step-text"><strong>OTP</strong><br>to your SIM</div>
        </div>
        <div class="flow-step">
            <div class="step-bubble">3</div>
            <div class="step-text"><strong>Confirm</strong><br>your identity</div>
        </div>
        <div class="flow-step">
            <div class="step-bubble">4</div>
            <div class="step-text"><strong>Access</strong><br>granted</div>
        </div>
    </div>

    <div class="card card-accent">
        <form method="POST" action="/3fa/start">
            <div class="form-group">
                <label>National Identification Number (NIN)</label>
                <input type="text" name="nin" required autofocus
                       placeholder="e.g. NIN-2026-001"
                       style="font-family:monospace;font-size:1.05rem;letter-spacing:0.05em;">
                <div class="form-hint">Try: NIN-2026-001</div>
            </div>
            <div class="form-group">
                <label>Portal Password</label>
                <input type="password" name="password" required placeholder="Your FNDIG portal password">
            </div>
            <button type="submit" class="btn btn-primary btn-full" style="margin-top:0.5rem;">Continue — Send OTP to SIM</button>
        </form>
    </div>
</div>
</body></html>
"""

# ─────────────────────────────────────────────────────────────
# Authenticated dashboard
# ─────────────────────────────────────────────────────────────
AUTHENTICATED_PAGE = BASE_CSS + """
{% set p = identity.profile %}
<div class="topbar">
    <div class="topbar-brand">
        <div class="topbar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21h18M3 10h18M5 6l7-3 7 3M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/>
            </svg>
        </div>
        <div>
            <div class="topbar-name">{{ name }}</div>
            <div class="topbar-meta">{{ sector }}</div>
        </div>
    </div>
    <div class="topbar-right">
        <a href="/logout">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                <polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
            Sign Out
        </a>
    </div>
</div>

<div class="container">
    {% for cat, msg in messages %}
    <div class="alert alert-{{ cat }}">{{ msg }}</div>
    {% endfor %}

    <!-- Welcome banner -->
    <div class="verified-banner">
        <div>
            <h2>Welcome, {{ p.first_name }} {{ p.last_name }}</h2>
            <p>Authenticated via FNDIG &middot; {{ identity.verified_at }} &middot; {{ identity.auth_method }}</p>
        </div>
        <div class="verified-chip">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"/>
            </svg>
            FNDIG Verified
        </div>
    </div>

    <!-- Personal details -->
    <div class="card">
        <div style="display:flex;align-items:center;gap:0.875rem;padding-bottom:1rem;margin-bottom:1rem;border-bottom:1px solid var(--border-subtle);">
            <div style="width:48px;height:48px;background:linear-gradient(135deg,#ea580c,#c2410c);border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                </svg>
            </div>
            <div style="flex:1;">
                <div style="font-size:1.15rem;font-weight:700;color:var(--text);letter-spacing:-0.02em;">
                    {{ p.first_name }} {% if p.middle_name %}{{ p.middle_name }} {% endif %}{{ p.last_name }}
                </div>
                <div style="font-size:0.8rem;color:var(--text-muted);font-family:monospace;">{{ identity.national_id }}</div>
            </div>
            <span class="badge badge-success">Verified</span>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem 1.5rem;">
            <div>
                <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Date of Birth</div>
                <div style="font-size:0.94rem;font-weight:500;">{{ p.date_of_birth }}</div>
            </div>
            <div>
                <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Gender</div>
                <div style="font-size:0.94rem;font-weight:500;">{{ p.gender }}</div>
            </div>
            <div>
                <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Phone</div>
                <div style="font-size:0.94rem;font-weight:500;font-family:monospace;">{{ p.phone }}</div>
            </div>
            <div>
                <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Email</div>
                <div style="font-size:0.94rem;font-weight:500;">{{ p.email or '—' }}</div>
            </div>
            <div>
                <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Address</div>
                <div style="font-size:0.94rem;font-weight:500;">{{ p.address }}</div>
            </div>
            <div>
                <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">State</div>
                <div style="font-size:0.94rem;font-weight:500;">{{ p.state }}</div>
            </div>
            <div>
                <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Nationality</div>
                <div style="font-size:0.94rem;font-weight:500;">{{ p.nationality }}</div>
            </div>
            <div>
                <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Occupation</div>
                <div style="font-size:0.94rem;font-weight:500;">{{ p.occupation }}</div>
            </div>
            <div>
                <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Marital Status</div>
                <div style="font-size:0.94rem;font-weight:500;">{{ p.marital_status }}</div>
            </div>
        </div>
    </div>

    <!-- Identity records -->
    <div class="card">
        <div class="card-title">Verified Identity Records — FNDIG Federated Sources</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.625rem;">
            <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                <div>
                    <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">NIMC · National ID (NIN)</div>
                    <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.nin }}</div>
                </div>
            </div>
            <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                <div>
                    <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">CBN/NIBSS · BVN</div>
                    <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.bvn }}</div>
                </div>
            </div>
            {% if p.vin %}
            <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                <div>
                    <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">INEC · Voter ID (VIN)</div>
                    <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.vin }}</div>
                </div>
            </div>
            {% endif %}
            {% if p.tin %}
            <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                <div>
                    <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">FIRS · Tax ID (TIN)</div>
                    <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.tin }}</div>
                </div>
            </div>
            {% endif %}
            {% if p.nhis %}
            <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                <div>
                    <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">NHIS · Health Insurance</div>
                    <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.nhis }}</div>
                </div>
            </div>
            {% endif %}
            {% if p.rsa %}
            <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                <div>
                    <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">PenCom · Pension RSA</div>
                    <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.rsa }}</div>
                </div>
            </div>
            {% endif %}
        </div>
    </div>

    <!-- Available services -->
    <div class="card">
        <div class="card-title">Available Services</div>
        <p style="font-size:0.875rem;color:var(--text-muted);margin-bottom:1.125rem;line-height:1.6;">
            Your identity is verified through FNDIG — access all services instantly, no paperwork required.
        </p>
        <div class="service-grid">
            <div class="service-card">
                <div class="svc-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/>
                    </svg>
                </div>
                <h4>Open Account</h4>
                <p>Savings, current, or fixed deposit — instant onboarding</p>
            </div>
            <div class="service-card">
                <div class="svc-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
                    </svg>
                </div>
                <h4>Apply for Loan</h4>
                <p>Personal, business, or mortgage loan application</p>
            </div>
            <div class="service-card">
                <div class="svc-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/>
                    </svg>
                </div>
                <h4>Digital Wallet</h4>
                <p>Mobile money and digital payment services</p>
            </div>
            <div class="service-card">
                <div class="svc-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                    </svg>
                </div>
                <h4>Insurance</h4>
                <p>Health, auto, and life insurance enrollment</p>
            </div>
            <div class="service-card">
                <div class="svc-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>
                    </svg>
                </div>
                <h4>Investment</h4>
                <p>Stocks, bonds, and mutual fund accounts</p>
            </div>
            <div class="service-card">
                <div class="svc-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="2" y="5" width="20" height="14" rx="2"/>
                        <circle cx="8" cy="12" r="2"/><path d="M14 10h4M14 14h2"/>
                    </svg>
                </div>
                <h4>Card Services</h4>
                <p>Debit and credit card issuance</p>
            </div>
        </div>
    </div>
</div>
</body></html>
"""

# ─────────────────────────────────────────────────────────────
# OTP step (step 3 of 3)
# ─────────────────────────────────────────────────────────────
OTP_PAGE = BASE_CSS + """
<div class="topbar">
    <div class="topbar-brand">
        <div class="topbar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21h18M3 10h18M5 6l7-3 7 3M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/>
            </svg>
        </div>
        <div>
            <div class="topbar-name">{{ name }}</div>
            <div class="topbar-meta">{{ sector }}</div>
        </div>
    </div>
</div>

<div class="container-sm">
    {% for cat, msg in messages %}
    <div class="alert alert-{{ cat }}">{{ msg }}</div>
    {% endfor %}

    <!-- Step progress -->
    <div class="flow-steps" style="margin-bottom:1.75rem;">
        <div class="flow-step done">
            <div class="step-bubble"></div>
            <div class="step-text">NIN &amp; Password</div>
        </div>
        <div class="flow-step active">
            <div class="step-bubble">2</div>
            <div class="step-text">OTP Code</div>
        </div>
        <div class="flow-step">
            <div class="step-bubble">3</div>
            <div class="step-text">Confirm</div>
        </div>
        <div class="flow-step">
            <div class="step-bubble">4</div>
            <div class="step-text">Access</div>
        </div>
    </div>

    <div class="card">
        <div class="card-title">Step 2 — Enter OTP from your SIM</div>
        <p style="font-size:0.875rem; color:var(--text-muted); margin-bottom:1.125rem; line-height:1.6;">
            NIN and password verified. A one-time code has been sent to
            <strong style="color:var(--text);">{{ masked_phone }}</strong>.
        </p>
        <form method="POST" action="/3fa/verify-otp">
            <div class="form-group">
                <label>OTP Code</label>
                <input type="text" name="code" required maxlength="6" autofocus
                       placeholder="000000"
                       style="font-size:1.5rem; letter-spacing:0.25em; text-align:center; font-family:monospace; font-weight:700;">
            </div>
            <button type="submit" class="btn btn-primary btn-full">Complete Sign-In</button>
        </form>
    </div>
</div>
</body></html>
"""

# ─────────────────────────────────────────────────────────────
# Manual KYC form
# ─────────────────────────────────────────────────────────────
MANUAL_KYC_PAGE = BASE_CSS + """
<div class="topbar">
    <div class="topbar-brand">
        <div class="topbar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21h18M3 10h18M5 6l7-3 7 3M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/>
            </svg>
        </div>
        <div>
            <div class="topbar-name">{{ name }}</div>
            <div class="topbar-meta">{{ sector }}</div>
        </div>
    </div>
    <div class="topbar-right">
        <a href="/dashboard">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="15 18 9 12 15 6"/>
            </svg>
            Back to Dashboard
        </a>
    </div>
</div>

<div class="container-sm">
    {% for cat, msg in messages %}
    <div class="alert alert-{{ cat }}">{{ msg }}</div>
    {% endfor %}

    <div class="card card-accent">
        <div class="card-title">Manual KYC Required</div>

        <div class="alert alert-warning">
            FIG could not verify your <strong>{{ category }}</strong> identity: {{ reason }}
        </div>

        <p style="font-size:0.875rem; color:var(--text); font-weight:600; margin-bottom:0.5rem;">{{ nudge }}</p>

        <p style="font-size:0.875rem; color:var(--text-muted); margin-bottom:1.25rem; line-height:1.65;">
            Because we don't have this on file, please upload <em>any</em> supporting document
            (ID card, utility bill, photo, PDF — anything works in this demo).
            On submit, <strong>{{ name }}</strong> will accept the file as proof and register the
            <strong>{{ category }}</strong> category as filled on your FIG profile, so no
            other institution will ever have to ask you for it again.
        </p>

        <form method="POST" action="/manual-kyc-submit" enctype="multipart/form-data">
            <input type="hidden" name="category" value="{{ category }}">
            <div class="form-group">
                <label>Full Legal Name</label>
                <input type="text" name="full_name" placeholder="As it appears on your ID">
            </div>
            <div class="form-group">
                <label>Supporting Document</label>
                <input type="file" name="document" required
                       style="padding:0.45rem 0.75rem; cursor:pointer;">
                <div class="form-hint">Accepts any file type: PDF, JPG, PNG, DOCX, etc.</div>
            </div>
            <button type="submit" class="btn btn-primary btn-full">Submit Manual KYC</button>
        </form>
    </div>
</div>
</body></html>
"""

# ─────────────────────────────────────────────────────────────
# Manual KYC success
# ─────────────────────────────────────────────────────────────
MANUAL_KYC_SUCCESS_PAGE = BASE_CSS + """
<div class="topbar">
    <div class="topbar-brand">
        <div class="topbar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21h18M3 10h18M5 6l7-3 7 3M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/>
            </svg>
        </div>
        <div>
            <div class="topbar-name">{{ name }}</div>
            <div class="topbar-meta">{{ sector }}</div>
        </div>
    </div>
    <div class="topbar-right">
        <a href="/dashboard">Back to Dashboard</a>
    </div>
</div>

<div class="container-sm">
    <div class="card card-success" style="margin-top:0.5rem;">
        <div style="text-align:center; padding:1rem 0 1.25rem;">
            <div style="width:56px; height:56px; background:var(--success-bg); border-radius:50%; display:flex; align-items:center; justify-content:center; margin:0 auto 1rem;">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"/>
                </svg>
            </div>
            <div style="font-size:1.1rem; font-weight:700; color:var(--text); margin-bottom:0.25rem;">Manual KYC Accepted</div>
            <div style="font-size:0.875rem; color:var(--text-muted);">Your identity has been updated across the FIG network</div>
        </div>

        <div class="alert alert-success" style="text-align:left;">
            We received <strong>{{ filename }}</strong> ({{ size }} bytes) and accepted it as proof of
            <strong>{{ category }}</strong>.
        </div>

        <p style="font-size:0.875rem; color:var(--text-muted); margin-bottom:0.875rem; line-height:1.65;">
            Your FIG profile has been updated — the <strong>{{ category }}</strong> category is now marked
            complete and any other institution that needs it will see it instantly. No further manual
            KYC will be required for this category.
        </p>

        <p style="font-size:0.78rem; color:var(--text-subtle); margin-bottom:1.25rem; font-family:monospace;">
            Reference: {{ proof_ref }}
        </p>

        <a href="/dashboard" class="btn btn-success btn-full">Continue to {{ name }}</a>
    </div>
</div>
</body></html>
"""

# ─────────────────────────────────────────────────────────────
# Verification requested (waiting for citizen consent)
# ─────────────────────────────────────────────────────────────
VERIFICATION_REQUESTED_PAGE = BASE_CSS + """
<div class="topbar">
    <div class="topbar-brand">
        <div class="topbar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21h18M3 10h18M5 6l7-3 7 3M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/>
            </svg>
        </div>
        <div>
            <div class="topbar-name">{{ name }}</div>
            <div class="topbar-meta">{{ sector }}</div>
        </div>
    </div>
</div>

<div class="container-sm">
    <div class="card" style="margin-top:0.5rem;">
        <div class="card-title">Verification Requested</div>

        <div class="info-box" style="margin-bottom:1.25rem;">
            <p>
                <strong>Request ID: #{{ request_id }}</strong><br>
                A verification request has been sent to the FIG Gateway for
                National ID <strong>{{ national_id }}</strong>.
            </p>
        </div>

        <!-- Step flow -->
        <div class="flow-steps" style="margin-bottom:1.5rem;">
            <div class="flow-step done">
                <div class="step-bubble"></div>
                <div class="step-text">Request Sent</div>
            </div>
            <div class="flow-step">
                <div class="step-bubble">2</div>
                <div class="step-text">Citizen Approves in FIG Portal</div>
            </div>
            <div class="flow-step">
                <div class="step-bubble">3</div>
                <div class="step-text">Gateway Responds</div>
            </div>
            <div class="flow-step">
                <div class="step-bubble">4</div>
                <div class="step-text">Access Granted</div>
            </div>
        </div>

        <p style="font-size:0.875rem; color:var(--text-muted); margin-bottom:1.25rem; line-height:1.65;">
            The citizen needs to approve this request in their
            <strong style="color:var(--text);">FIG Citizen Portal</strong>
            at <a href="http://localhost:5002/portal" style="color:var(--info);">http://localhost:5002/portal</a>.
            Once approved, click the button below to check the status.
        </p>

        <div style="display:flex; gap:0.75rem; flex-wrap:wrap; margin-bottom:1rem;">
            <form method="POST" action="/check-verification">
                <input type="hidden" name="request_id" value="{{ request_id }}">
                <button type="submit" class="btn btn-primary">Check Verification Status</button>
            </form>
            <a href="/" class="btn btn-outline">Back to Login</a>
        </div>

        {% if result %}
        <div style="margin-top:1rem; border-top:1px solid var(--border-subtle); padding-top:1rem;">
            {% if result.status == 'approved' %}
            <div class="alert alert-success">
                Verification approved.
                <a href="/" style="color:#065f46; font-weight:600; margin-left:0.25rem;">Proceed to sign in with token →</a>
            </div>
            {% elif result.status == 'pending' %}
            <div class="alert alert-warning">Still pending — the citizen has not yet approved the request.</div>
            {% else %}
            <div class="alert alert-error">Verification {{ result.status }}. {{ result.get('result', {}).get('reason', '') }}</div>
            {% endif %}
            <div class="result-box">{{ result | tojson(indent=2) }}</div>
        </div>
        {% endif %}
    </div>
</div>
</body></html>
"""


# ─────────────────────────────────────────────────────────────
# Identity confirmation (shown after 3FA passes, before dashboard)
# ─────────────────────────────────────────────────────────────
IDENTITY_CONFIRM_PAGE = BASE_CSS + """
<div class="topbar">
    <div class="topbar-brand">
        <div class="topbar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21h18M3 10h18M5 6l7-3 7 3M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/>
            </svg>
        </div>
        <div>
            <div class="topbar-name">{{ name }}</div>
            <div class="topbar-meta">{{ sector }} &middot; Powered by FNDIG</div>
        </div>
    </div>
    <div class="topbar-right">
        <div style="display:flex;align-items:center;gap:0.35rem;font-size:0.8rem;color:#34d399;">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"/>
            </svg>
            3FA Passed
        </div>
    </div>
</div>

<div class="container">
    <div style="max-width:680px; margin:0 auto;">

        <div style="text-align:center; padding:2rem 0 1.75rem;">
            <div style="width:60px;height:60px;background:#ecfdf5;border:2px solid #a7f3d0;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 1rem;">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"/>
                </svg>
            </div>
            <h2 style="font-size:1.375rem;font-weight:800;color:var(--text);letter-spacing:-0.02em;margin-bottom:0.375rem;">
                Identity Verified by FNDIG
            </h2>
            <p style="font-size:0.9rem;color:var(--text-muted);max-width:420px;margin:0 auto;line-height:1.65;">
                The gateway returned the following verified record for UIDT
                <strong style="font-family:monospace;color:var(--text);">{{ national_id }}</strong>.
                Confirm this is you to access {{ name }} services.
            </p>
        </div>

        <!-- Full profile card -->
        <div class="card" style="margin-bottom:1.25rem;">
            <div style="display:flex;align-items:center;gap:0.875rem;padding-bottom:1rem;margin-bottom:1rem;border-bottom:1px solid var(--border-subtle);">
                <div style="width:48px;height:48px;background:linear-gradient(135deg,#059669,#34d399);border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                    </svg>
                </div>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:1.15rem;font-weight:700;color:var(--text);letter-spacing:-0.02em;">
                        {{ p.first_name }} {% if p.middle_name %}{{ p.middle_name }} {% endif %}{{ p.last_name }}
                    </div>
                    <div style="font-size:0.8rem;color:var(--text-muted);">{{ national_id }} &middot; FNDIG Verified Identity</div>
                </div>
                <span class="badge badge-success">Verified</span>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem 1.5rem;">
                <div>
                    <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Date of Birth</div>
                    <div style="font-size:0.94rem;font-weight:500;">{{ p.date_of_birth }}</div>
                </div>
                <div>
                    <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Gender</div>
                    <div style="font-size:0.94rem;font-weight:500;">{{ p.gender }}</div>
                </div>
                <div>
                    <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Phone</div>
                    <div style="font-size:0.94rem;font-weight:500;font-family:monospace;">{{ p.phone }}</div>
                </div>
                <div>
                    <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Email</div>
                    <div style="font-size:0.94rem;font-weight:500;">{{ p.email or '—' }}</div>
                </div>
                <div>
                    <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Address</div>
                    <div style="font-size:0.94rem;font-weight:500;">{{ p.address }}</div>
                </div>
                <div>
                    <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">State</div>
                    <div style="font-size:0.94rem;font-weight:500;">{{ p.state }}</div>
                </div>
                <div>
                    <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Nationality</div>
                    <div style="font-size:0.94rem;font-weight:500;">{{ p.nationality }}</div>
                </div>
                <div>
                    <div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-subtle);margin-bottom:0.2rem;">Occupation</div>
                    <div style="font-size:0.94rem;font-weight:500;">{{ p.occupation }}</div>
                </div>
            </div>
        </div>

        <!-- Identity records across sources -->
        <div class="card" style="margin-bottom:1.25rem;">
            <div class="card-title">Verified Identity Records from Government Databases</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.625rem;">

                <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    <div>
                        <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">NIMC · National ID (NIN)</div>
                        <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.nin }}</div>
                    </div>
                </div>

                <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    <div>
                        <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">CBN/NIBSS · BVN</div>
                        <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.bvn }}</div>
                    </div>
                </div>

                {% if p.vin %}
                <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    <div>
                        <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">INEC · Voter ID (VIN)</div>
                        <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.vin }}</div>
                    </div>
                </div>
                {% endif %}

                {% if p.tin %}
                <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    <div>
                        <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">FIRS · Tax ID (TIN)</div>
                        <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.tin }}</div>
                    </div>
                </div>
                {% endif %}

                {% if p.nhis %}
                <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    <div>
                        <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">NHIS · Health Insurance</div>
                        <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.nhis }}</div>
                    </div>
                </div>
                {% endif %}

                {% if p.rsa %}
                <div style="display:flex;align-items:center;gap:0.625rem;padding:0.625rem 0.875rem;border:1px solid #bbf7d0;border-radius:8px;background:#f0fdf4;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    <div>
                        <div style="font-size:0.72rem;font-weight:600;color:var(--text-muted);">PenCom · Pension RSA</div>
                        <div style="font-size:0.82rem;font-weight:600;font-family:monospace;color:var(--text);">{{ p.rsa }}</div>
                    </div>
                </div>
                {% endif %}

            </div>
        </div>

        <!-- Confirm action -->
        <div class="card" style="border-color:#bbf7d0;background:#f0fdf4;">
            <p style="font-size:0.875rem;color:#065f46;margin-bottom:1.125rem;line-height:1.65;">
                <strong>This is what {{ name }} received from FNDIG.</strong>
                No raw data is stored by the bank — only a confirmation that your identity is valid.
                Click below to grant consent and access your banking services.
            </p>
            <div style="display:flex;gap:0.75rem;flex-wrap:wrap;">
                <form method="POST" action="/identity-confirm">
                    <button type="submit" class="btn btn-success" style="padding:0.65rem 1.5rem;font-size:0.9rem;">
                        Yes, this is me — Access Services
                    </button>
                </form>
                <a href="/logout" class="btn btn-outline">That's not me — Sign out</a>
            </div>
        </div>

    </div>
</div>
</body></html>
"""


# ─── Routes ────────────────────────────────────────────────

@app.route('/')
def index():
    if 'identity' in session:
        return redirect(url_for('dashboard'))
    messages = session.pop('_messages', [])
    return render_template_string(LOGIN_PAGE, name=INSTITUTION_NAME,
                                 sector=INSTITUTION_SECTOR, messages=messages)


@app.route('/authenticate', methods=['POST'])
def authenticate():
    """Disabled. Token-only sign-in is no longer permitted -- the institution
    requires the full 3-factor flow (token + password + SIM OTP). This route
    is kept only to surface a clear message to anything still wired to it."""
    _flash('Token-only sign-in has been disabled for security. Please use the 3-Factor Sign-In flow.', 'error')
    return redirect('/')


@app.route('/request-verification', methods=['POST'])
def request_verification():
    """Institution requests verification via National ID (requires citizen consent)."""
    national_id = request.form.get('national_id', '').strip()
    verification_type = request.form.get('verification_type', 'identity')

    if not INSTITUTION_API_KEY:
        _flash('Institution API key not configured. Run the FIG Gateway first.', 'error')
        return redirect('/')

    try:
        resp = requests.post(
            f'{FIG_GATEWAY_URL}/api/v1/verify',
            json={
                'national_id': national_id,
                'verification_type': verification_type,
                'consent_required': True
            },
            headers={'X-API-Key': INSTITUTION_API_KEY},
            timeout=10
        )
        data = resp.json()
    except requests.RequestException as e:
        _flash(f'Cannot reach FIG Gateway: {e}', 'error')
        return redirect('/')

    if 'request_id' in data:
        return render_template_string(VERIFICATION_REQUESTED_PAGE,
                                      name=INSTITUTION_NAME, sector=INSTITUTION_SECTOR,
                                      request_id=data['request_id'],
                                      national_id=national_id, result=None)
    else:
        _flash(f'Error: {data.get("error", "Unknown")}', 'error')
        return redirect('/')


@app.route('/check-verification', methods=['POST'])
def check_verification():
    """Check the status of a pending verification request."""
    request_id = request.form.get('request_id')

    try:
        resp = requests.get(
            f'{FIG_GATEWAY_URL}/api/v1/verify/{request_id}',
            headers={'X-API-Key': INSTITUTION_API_KEY},
            timeout=10
        )
        data = resp.json()
    except requests.RequestException as e:
        _flash(f'Cannot reach FIG Gateway: {e}', 'error')
        return redirect('/')

    return render_template_string(VERIFICATION_REQUESTED_PAGE,
                                  name=INSTITUTION_NAME, sector=INSTITUTION_SECTOR,
                                  request_id=request_id, national_id='(from request)',
                                  result=data)


def _refresh_pending_history():
    """Poll FIG for every verification that is still pending in our cache,
    so that once the citizen grants consent the pulled data is reflected in
    the bank dashboard without the user having to click anything."""
    history = session.get('verification_history', [])
    updated = False
    for entry in history:
        if entry.get('status') != 'pending':
            continue
        try:
            r = requests.get(
                f'{FIG_GATEWAY_URL}/api/v1/verify/{entry["id"]}',
                headers={'X-API-Key': INSTITUTION_API_KEY},
                timeout=5,
            ).json()
        except requests.RequestException:
            continue
        new_status = r.get('status', 'pending')
        if new_status != 'pending':
            entry['status'] = new_status
            # Keep the result as a real dict so the template can show fields
            entry['result'] = r.get('result') or {}
            updated = True
    if updated:
        session['verification_history'] = history


@app.route('/dashboard')
def dashboard():
    if 'identity' not in session:
        if 'pending_identity' in session:
            return redirect('/identity-confirm')
        return redirect('/')
    _refresh_pending_history()
    messages = session.pop('_messages', [])
    return render_template_string(AUTHENTICATED_PAGE,
                                  name=INSTITUTION_NAME, sector=INSTITUTION_SECTOR,
                                  identity=session['identity'],
                                  verification_history=session.get('verification_history', []),
                                  messages=messages)


@app.route('/additional-verification', methods=['POST'])
def additional_verification():
    """Request additional verification for an already-authenticated citizen."""
    if 'identity' not in session:
        return redirect('/')

    verification_type = request.form.get('verification_type', 'kyc')
    national_id = session['identity']['national_id']

    try:
        resp = requests.post(
            f'{FIG_GATEWAY_URL}/api/v1/verify',
            json={
                'national_id': national_id,
                'verification_type': verification_type,
                'consent_required': True
            },
            headers={'X-API-Key': INSTITUTION_API_KEY},
            timeout=10
        )
        data = resp.json()
    except requests.RequestException as e:
        _flash(f'Cannot reach FIG Gateway: {e}', 'error')
        return redirect(url_for('dashboard'))

    history = session.get('verification_history', [])
    if 'request_id' in data:
        entry = {
            'id': data['request_id'],
            'type': verification_type,
            'status': data.get('status', 'pending'),
            'result': data.get('result') or {}
        }
        history.append(entry)
        session['verification_history'] = history
        _flash(f'Verification request #{data["request_id"]} submitted. Citizen must approve in FIG Portal.', 'success')
    else:
        _flash(f'Error: {data.get("error", "Unknown")}', 'error')

    return redirect(url_for('dashboard'))


@app.route('/3fa/start', methods=['POST'])
def three_fa_start():
    """Step 1+2: validate NIN, accept any password (demo), then show OTP step."""
    nin = request.form.get('nin', '').strip().upper()

    if not nin:
        _flash('Please enter your National ID (NIN).', 'error')
        return redirect('/')

    # Look up citizen by NIN — works for all 3 demo profiles + any NIN
    profile = _get_demo_profile(nin)
    phone = profile.get('phone', '0800-000-0000')
    # Mask phone for display: show first 4 and last 4 digits
    digits = phone.replace('-', '')
    masked = f"{digits[:4]}{'*' * max(0, len(digits) - 8)}{digits[-4:]}" if len(digits) >= 8 else phone

    session['3fa_nin'] = nin
    return render_template_string(OTP_PAGE, name=INSTITUTION_NAME,
                                  sector=INSTITUTION_SECTOR,
                                  masked_phone=masked,
                                  demo_code='123456',
                                  messages=session.pop('_messages', []))


@app.route('/3fa/verify-otp', methods=['POST'])
def three_fa_verify_otp():
    code = request.form.get('code', '').strip()
    nin = session.get('3fa_nin')
    if not nin:
        _flash('Session expired. Please sign in again.', 'error')
        return redirect('/')
    if code != '123456':
        _flash('Incorrect OTP. (Demo: use 123456)', 'error')
        return render_template_string(OTP_PAGE, name=INSTITUTION_NAME,
                                      sector=INSTITUTION_SECTOR,
                                      masked_phone='****',
                                      demo_code='123456',
                                      messages=session.pop('_messages', []))

    # Store verified identity temporarily, pending citizen confirmation
    session['pending_identity'] = {
        'national_id': nin,
        'verified_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        'auth_method': '3FA (NIN + password + SIM OTP)',
    }
    return redirect('/identity-confirm')


@app.route('/identity-confirm', methods=['GET', 'POST'])
def identity_confirm():
    """Show the citizen's full FNDIG profile and ask them to confirm before dashboard access."""
    pending = session.get('pending_identity')
    if not pending:
        if 'identity' in session:
            return redirect(url_for('dashboard'))
        return redirect('/')

    national_id = pending['national_id']
    profile = _get_demo_profile(national_id)

    if request.method == 'POST':
        # Citizen confirmed — promote to full session identity, include profile
        session['identity'] = {**pending, 'profile': profile}
        session.pop('pending_identity', None)
        session['verification_history'] = []
        _flash('Welcome — your identity has been confirmed. You now have full access.', 'success')
        return redirect(url_for('dashboard'))

    return render_template_string(
        IDENTITY_CONFIRM_PAGE,
        name=INSTITUTION_NAME, sector=INSTITUTION_SECTOR,
        national_id=national_id, p=profile,
        messages=session.pop('_messages', []),
    )


@app.route('/category-verify', methods=['POST'])
def category_verify():
    """Try a category-scoped verify; fall back to manual KYC if missing."""
    if 'identity' not in session:
        return redirect('/')
    try:
        r = requests.post(f'{FIG_GATEWAY_URL}/api/v1/verify/category',
                          json={'national_id': session['identity']['national_id'],
                                'category': INSTITUTION_REQUIRED_CATEGORY},
                          headers={'X-API-Key': INSTITUTION_API_KEY}, timeout=10).json()
    except requests.RequestException as e:
        _flash(f'Gateway unreachable: {e}', 'error')
        return redirect(url_for('dashboard'))

    if r.get('manual_kyc_required'):
        return render_template_string(MANUAL_KYC_PAGE, name=INSTITUTION_NAME,
                                      sector=INSTITUTION_SECTOR,
                                      category=r.get('category', INSTITUTION_REQUIRED_CATEGORY),
                                      reason=r.get('reason', ''),
                                      nudge=r.get('nudge', ''),
                                      messages=session.pop('_messages', []))
    _flash(f"{INSTITUTION_REQUIRED_CATEGORY} verified via FIG (record id: {r.get('record_id')})", 'success')
    return redirect(url_for('dashboard'))


@app.route('/manual-kyc-submit', methods=['POST'])
def manual_kyc_submit():
    """Accept any file as manual KYC proof, save it locally, and tell FIG
    to register the corresponding identity category for the citizen so the
    gap is closed for every future institution."""
    if 'identity' not in session:
        return redirect('/')

    category = request.form.get('category', '').strip()
    full_name = request.form.get('full_name', '').strip()
    f = request.files.get('document')
    if not category or not f or not f.filename:
        _flash('Please attach a file.', 'error')
        return redirect('/')

    # 1. Persist the file locally (any extension is allowed)
    upload_dir = os.path.join(os.path.dirname(__file__), 'manual_kyc_uploads')
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = secure_filename(f.filename) or 'upload.bin'
    stamped = f"{int(datetime.utcnow().timestamp())}_{session['identity']['national_id']}_{safe_name}"
    full_path = os.path.join(upload_dir, stamped)
    f.save(full_path)
    size = os.path.getsize(full_path)

    # 2. Tell FIG: the citizen has now satisfied this category via our manual KYC
    proof_ref = f'manual_kyc_uploads/{stamped}'
    try:
        r = requests.post(
            f'{FIG_GATEWAY_URL}/api/v1/identity/manual-register',
            json={
                'national_id': session['identity']['national_id'],
                'category': category,
                'manual_proof_ref': proof_ref,
                'collected_by': INSTITUTION_NAME,
                'holder_name': full_name,
            },
            headers={'X-API-Key': INSTITUTION_API_KEY},
            timeout=10,
        ).json()
    except requests.RequestException as e:
        _flash(f'File saved locally but FIG registration failed: {e}', 'error')
        return redirect('/dashboard')

    if not r.get('registered'):
        _flash(f'FIG rejected the manual proof: {r.get("error", "unknown")}', 'error')
        return redirect('/dashboard')

    return render_template_string(
        MANUAL_KYC_SUCCESS_PAGE,
        name=INSTITUTION_NAME, sector=INSTITUTION_SECTOR,
        category=category, filename=safe_name, size=size,
        proof_ref=proof_ref, messages=[],
    )


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


def _flash(msg, cat):
    msgs = session.get('_messages', [])
    msgs.append((cat, msg))
    session['_messages'] = msgs


def get_institution_api_key():
    """Fetch the institution API key — from env var (Render) or gateway DB (local)."""
    global INSTITUTION_API_KEY
    if INSTITUTION_API_KEY:
        print(f'[*] Using API key from environment variable.')
        return
    try:
        import sys
        sys.path.insert(0, '.')
        from app import app as gateway_app
        from models import Institution
        with gateway_app.app_context():
            inst = Institution.query.filter_by(name='National Bank').first()
            if inst:
                INSTITUTION_API_KEY = inst.api_key
                print(f'[*] Using API key from institution: {inst.name}')
            else:
                print('[!] No institution found. Register one in the FIG Gateway first.')
    except Exception as e:
        print(f'[!] Could not load API key from gateway DB: {e}')
        print('[!] Set INSTITUTION_API_KEY env var to bypass this.')


get_institution_api_key()

if __name__ == '__main__':
    print('=' * 60)
    print('  Demo Institution Portal: National Bank of Nigeria')
    print('  Authenticates citizens via FIG Gateway credentials')
    print('=' * 60)
    print(f'[*] FIG Gateway: {FIG_GATEWAY_URL}')
    print('[*] This demo runs on http://localhost:5001')
    print()
    app.run(debug=True, host='0.0.0.0', port=5001)
