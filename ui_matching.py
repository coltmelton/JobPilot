"""Streamlit views for local resume analysis and explainable recommendations."""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from db import DATA, profile, save_profile
from matching import assess_job, estimate_experience, extract_resume, resume_fingerprint, skills_in


def render_resume():
    st.subheader('Resume & Matching')
    st.caption('Resume parsing and ranking run locally. Your resume text is not sent to job boards or an AI provider. Matching is a rule-based shortlist, not an eligibility decision.')
    applicant = profile()
    saved = applicant.get('matching', {})
    folder = DATA/'documents'
    files = sorted(path.name for path in folder.glob('*') if path.is_file() and path.suffix.lower() in ('.pdf', '.docx', '.txt')) if folder.exists() else []
    options = ['Paste text manually'] + files
    previous = saved.get('resume_file', '')
    selected = st.selectbox('Resume used for matching', options, index=options.index(previous) if previous in options else 0)
    if st.button('Extract resume text', disabled=selected == options[0]):
        try:
            path = (folder/selected).resolve()
            if path.parent != folder.resolve():
                raise ValueError('Choose a file in Documents.')
            text = extract_resume(path)
            estimate = estimate_experience(text)
            st.session_state['resume_draft_text'] = text
            st.session_state['resume_draft_years'] = float(estimate['years'] or 0)
            st.session_state['resume_draft_confirmed'] = False
            st.success('Text extracted. Review dates and relevant experience before saving.')
        except ImportError:
            st.error('Resume reader is missing. Run setup.cmd, then restart the app.')
        except Exception as exc:
            st.error(f'Could not read resume: {exc}')
    with st.form('matching_profile'):
        text = st.text_area('Resume text (review or paste here)', value=saved.get('text', ''), height=300, key='resume_draft_text')
        years = st.number_input('Years of relevant experience for matching', min_value=0.0, max_value=60.0, step=0.1, value=float(saved.get('years_experience') or 0), key='resume_draft_years')
        confirmed = st.checkbox('I reviewed the experience baseline (including whether internships / part-time work count)', value=saved.get('experience_confirmed', False), key='resume_draft_confirmed')
        st.caption('The calendar estimate may include internships, co-ops and part-time work. Adjust it for the roles you want; employers may count experience differently.')
        if st.form_submit_button('Save matching profile'):
            if len(text.strip()) < 50:
                st.error('Paste or extract a readable resume before saving.')
            else:
                # Reload so saving this page never overwrites other profile edits.
                applicant = profile()
                applicant['matching'] = {'text': text.strip(), 'resume_file': selected if selected in files else '',
                    'years_experience': years, 'experience_confirmed': confirmed,
                    'fingerprint': resume_fingerprint(text.strip()), 'estimate': estimate_experience(text)}
                save_profile(applicant)
                saved = applicant['matching']
                st.success('Matching profile saved. Discovery and queued-job rankings use it immediately.')
    if saved.get('text'):
        estimate = estimate_experience(saved['text'])
        st.write('Detected skills: ' + (', '.join(skills_in(saved['text'])) or 'No listed dictionary skills detected; matching may be limited.'))
        if estimate['years'] is not None:
            st.write(f"Estimated calendar experience: {estimate['years']:g} years")
            st.caption(estimate['note'])
            with st.expander('Dates used for the estimate'):
                st.write(estimate['evidence'])
        else:
            st.info('Employment date ranges could not be identified reliably. Enter your relevant years manually.')
        st.caption('Clearance for matching: ' + applicant.get('clearance_level', 'Not provided') + '. Edit this in My Profile. Ability to obtain a clearance is never assumed.')


def rank_and_filter(candidates, prefix='discovery'):
    applicant = profile()
    enabled = st.checkbox('Rank and filter using my resume', value=bool(applicant.get('matching', {}).get('text')), key=f'{prefix}_rank_enabled')
    if not enabled:
        return candidates
    if not applicant.get('matching', {}).get('text'):
        st.info('Set up Resume & Matching first. Clearance checks still use your profile.')
    st.caption('Higher scores mean more detected skill overlap, not a hiring probability. Missing descriptions and ambiguous requirements remain Needs review. No-clearance profiles retain jobs that allow obtaining a clearance later.')
    left, right = st.columns(2)
    hide_clearance = left.checkbox('Hide existing-clearance mismatches', value=True, key=f'{prefix}_hide_clearance')
    hide_experience = right.checkbox('Hide experience stretches', value=bool(applicant.get('matching', {}).get('experience_confirmed')), key=f'{prefix}_hide_experience')
    score = st.slider('Minimum match score', 0, 100, 0, key=f'{prefix}_min_score')
    ranked = [dict(job, **assess_job(job, applicant)) for job in candidates]
    visible = [job for job in ranked if job['match_score'] >= score
        and (not hide_clearance or job['match'] != 'Clearance mismatch')
        and (not hide_experience or job['experience_fit'] != 'Above your experience')]
    st.caption(f'{len(visible)} of {len(ranked)} candidates remain after matching filters. Turn off filters to inspect excluded jobs.')
    return sorted(visible, key=lambda item: item['match_score'], reverse=True)


def explain_candidates(candidates):
    if not candidates:
        return
    with st.expander('Why a job matched / requirements evidence'):
        options = {f"{index+1}. {job['company']} — {job['title']}": index for index, job in enumerate(candidates)}
        selected = st.selectbox('Inspect a match', list(options))
        job = candidates[options[selected]]
        assessment = assess_job(job, profile())
        st.write(f"{assessment['match']} · score {assessment['match_score']}/100")
        st.text(assessment['match_reasons'])
        st.write('Clearance: ' + assessment['clearance'])
        st.text(assessment['clearance_evidence'] or 'No explicit wording detected; verify the full posting.')
        st.text(assessment['experience_evidence'] or 'No numeric experience requirement detected.')
        st.caption('Description status: ' + assessment['description_status'])
        st.link_button('Verify full posting', job['url'])
        if job.get('description'):
            from matching import plain_text
            st.text_area('Job description used for matching', value=plain_text(job['description']), height=240, disabled=True)
