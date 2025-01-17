"""
Main web page controller.
Handles database connections, login, errors and basic routes.
Can be invoqued as a script to run a local server for testing/development.
"""

from flask import *

from app import app
from database import db
from user import User
from auth import auth
from admin import admin
import rest_interface
import xmlrpc_interface
import atexit
import cron
from apscheduler.schedulers.background import BackgroundScheduler
import logging
from waitress import serve

log = logging.getLogger('apscheduler.executors.default')
log.setLevel(logging.INFO)  # DEBUG

fmt = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
h = logging.StreamHandler()
h.setFormatter(fmt)
log.addHandler(h)


###############################################################################
# Main script body
###############################################################################

def run_middleware():
    scheduler = BackgroundScheduler()
    scheduler.add_job(cron.check_sync_data, 'interval', seconds=30)
    # Explicitly kick off the background thread
    scheduler.start()

    atexit.register(lambda: scheduler.shutdown(wait=False))
    #app.run(host="0.0.0.0")
    serve(app, host='0.0.0.0', port=5000)



if __name__ == "__main__":
    # This code is only executed if the cowlab.py file is directly called from
    # python and not imported from another python file / console.
    run_middleware()
