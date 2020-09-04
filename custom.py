# this file imports custom routes into the experiment server

from flask import Blueprint, render_template, request, jsonify, Response, abort, current_app
from jinja2 import TemplateNotFound
from functools import wraps
from sqlalchemy import or_

from psiturk.amt_services_wrapper import MTurkServicesWrapper
from psiturk.psiturk_config import PsiturkConfig
from psiturk.experiment_errors import ExperimentError
from psiturk.user_utils import PsiTurkAuthorization, nocache

# # Database setup
from psiturk.db import db_session, init_db
from psiturk.models import Participant
from json import dumps, loads

import re
import traceback

# load the configuration options
config = PsiturkConfig()
config.load_config()
# if you want to add a password protect route use this
myauth = PsiTurkAuthorization(config)

# explore the Blueprint
custom_code = Blueprint('custom_code', __name__,
                        template_folder='templates', static_folder='static')
_cached_wrapper = None
def getWrapper():
    global _cached_wrapper
    if not _cached_wrapper:
        wrapper = MTurkServicesWrapper(config=config, sandbox=False)
        wrapper.set_sandbox(False)
        _cached_wrapper = wrapper
    return _cached_wrapper

###########################################################
#  serving warm, fresh, & sweet custom, user-provided routes
#  add them here
###########################################################

@custom_code.route('/view_data')
@myauth.requires_auth
def list_my_data():
    query = Participant.query
    if "status" in request.args:
        query = query.filter(Participant.status == request.args["status"])
    if "hitid" in request.args:
        query = query.filter(Participant.hitid == request.args["hitid"])
    if "bonus" in request.args:
        if "-" in request.args["bonus"]:
            query = query.filter(Participant.bonus < 0)
        else:
            query = query.filter(Participant.bonus >= 0)
    query = query.order_by(Participant.beginhit.desc())
    users = query.all()
    try:
        return render_template('list.html', participants=users)
    except TemplateNotFound:
        abort(404)

def get_participant(args):
    users = Participant.query.filter(Participant.uniqueid == args["uniqueid"]).all()
    if len(users) != 1:
        raise ExperimentError("Found " + str(len(users)) + " users")
    return users[0]

@custom_code.route('/reject_one')
@myauth.requires_auth
def reject_one():
    try:
        resp = {
            "reject": str(getWrapper().reject_assignment(get_participant(request.args).assignmentid))
        }
    except Exception as e:
        resp = {
            "reject": "failure",
            "exception": str(e)
        }
    finally:
        return jsonify(**resp)

@custom_code.route('/approve_one')
@myauth.requires_auth
def approve_one():
    try:
        resp = {
            "approve": str(getWrapper().approve_assignment_by_assignment_id(get_participant(request.args).assignmentid))
        }
    except Exception as e:
        resp = {
            "approve": "failure",
            "exception": str(e)
        }
    finally:
        return jsonify(**resp)

# ----------------------------------------------
# example computing bonus
# ----------------------------------------------


@custom_code.route('/compute_bonus', methods=['GET'])
def compute_bonus():
    # check that user provided the correct keys
    # errors will not be that gracefull here if being
    # accessed by the Javascrip client
    if not 'uniqueId' in request.args:
        raise ExperimentError('improper_inputs')
    uniqueId = request.args['uniqueId']

    try:
        # lookup user in database
        user = Participant.query.filter(Participant.uniqueid == uniqueId).one()
        user_data = loads(user.datastring)  # load datastring from JSON
        
        outcomes = []
        nGames = 85
        nBonusGames = 3
        basepay = 2.5
        bonus = 10
        loggedBonus = None

        for record in user_data['data']:  # for line in data file
            trial = record['trialdata']
            if not isinstance(trial, str):
                continue
            if "Main Game" in trial:
                match = re.search("Cost: (\\d+\\.\\d+)", trial)
                if match:
                    outcomes.append(float(match.group(1)))
            else:
                match = re.search("Displayed bonus: (\\d+\\.\\d+)", trial)
                if match:
                    loggedBonus = float(match.group(1))
        if len(outcomes) == 0:
            # This is a special value that means the user didn't make it to the main game
            user.bonus = -100
        elif len(outcomes) < nGames:
            ratio = min(len(outcomes) / nGames, 1)
            user.bonus = round(ratio * (bonus - basepay), 2)
        else:
            # Note that this is a replica of the algorithm in Secretay.cs pickGames()
            # This calculation should yield the exact same result
            outcomes.sort()
            for i in range(nBonusGames):
                ratio = (i + 1) / (nBonusGames + 1);
                bonus -= outcomes[int(len(outcomes) * ratio)]
            bonus = round(bonus, 2)
            if bonus == loggedBonus:
                user.bonus = bonus
            else:
                # Write a negative bonus to the database to indicate something didn't add up
                # Negative bonuses are easily identified and don't cost anything if they're accidentally paid out.
                user.bonus = -bonus
        db_session.add(user)
        db_session.commit()
        resp = {"bonusComputed": "success"}
    except Exception as e:
        traceback.print_exc()
        print(str(e))
        resp = {
            "bonusComputed": "failure",
            "exception": str(e)
        }
    finally:
        return jsonify(**resp)
