#!/bin/bash
# Start backend with pythonocc-core environment

source /home/nitrolinux/miniconda3/bin/activate
export PYTHONPATH="/home/nitrolinux/miniconda3/pkgs/pythonocc-core-7.9.3-all_he3b93f9_200/lib/python3.11/site-packages:$PYTHONPATH"

cd /home/nitrolinux/claude/plm2/backend

# Upgrade database
alembic upgrade head

# Copy legacy sep_risks rows into the risk_assessment forms (idempotent no-op
# once done; gate colour and sign-off read the form, not sep_risks).
python scripts/migrate_sep_risks.py

# Run the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
