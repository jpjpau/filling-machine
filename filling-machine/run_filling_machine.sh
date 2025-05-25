#!/usr/bin/env bash
cd /home/pi/filling-machine/filling-machine
# Activate the virtualenv
source venv/bin/activate
# Pull latest code
git pull origin main
# Run the program, tee’ing all output to run.log
python main.py 2>&1 | tee run.log