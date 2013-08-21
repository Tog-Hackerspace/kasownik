import hmac
import json
import datetime
from functools import wraps

from flask import request, abort, Response

from webapp import models, app

class APIError(Exception):
    def __init__(self, message):
        self.message = message

def _public_api_method(path):
    """A decorator that adds a public, GET based method at /api/<path>.json.

    The resulting data is JSON-serialized."""
    def decorator2(original):
        @wraps(original)
        def wrapper_json(*args, **kwargs):
            content = original(*args, **kwargs)
            
            last_transfer = models.Transfer.query.order_by(models.Transfer.date.desc()).first()
            modified = str(last_transfer.date)

            r = {}
            r["status"] = "ok"
            r["content"] = content
            r["modified"] = modified
            return Response(json.dumps(r), mimetype="application/json")
        return app.route("/api/" + path + ".json", methods=["GET"])(wrapper_json)
    return decorator2
            

def _private_api_method(path):
    """A decorator that adds a private, HMACed, POST based method at /api/path.
    The  JSON-decoded POSTbody is stored as request.decoded.
    The resulting data is also JSON-encoded.

    It also that ensures that the request is authorized if 'private' is True.
    If so, it also adds a request.api_member object that points to a member if an
    API key should be limited to that member (for example, when handing over
    keys to normal members)."""
    def decorator(original):
        @wraps(original)
        def wrapper(*args, **kwargs):
            if request.data.count(",") != 1:
                abort(400)
            message64, mac64 = request.data.split(",")
            try:
                message = message64.decode("base64")
                mac = mac64.decode("base64")
            except:
                abort(400)

            for key in models.APIKey.query.all():
                mac_verify = hmac.new(key.secret.encode("utf-8"))
                mac_verify.update(message)
                if mac_verify.digest() == mac:
                    break
            else:
                abort(403)

            if key.member:
                request.api_member = key.member
            else:
                request.api_member = None
            try:
                if request.data:
                    request.decoded = json.loads(request.data.decode("base64"))
                else:
                    request.decoded = {}
            except Exception as e:
                print request.data
                print e
                abort(400)

            return json.dumps(original(*args, **kwargs))
        return app.route("/api/" + path, methods=["POST"])(wrapper)
    return decorator

@_private_api_method("list_members")
def api_members():
    if request.api_member:
        abort(403)

    members = [member.username for member in models.Member.query.all()]
    return members


@_private_api_method("get_member_info")
def api_member():
    mid = request.decoded["member"]
    if request.api_member and request.api_member.username != mid:
        abort(403)

    member = models.Member.query.filter_by(username=mid).join(models.Member.transfers).\
        join(models.MemberTransfer.transfer).first()
    mts = member.transfers
    response = {}
    response["paid"] = []
    for mt in mts:
        t = {}
        t["year"] = mt.year
        t["month"] = mt.month
        transfer = {}
        transfer["uid"] = mt.transfer.uid
        transfer["amount"] = mt.transfer.amount
        transfer["title"] = mt.transfer.title
        transfer["account"] = mt.transfer.account_from
        transfer["from"] = mt.transfer.name_from
        t["transfer"] = transfer
        response["paid"].append(t)
    response["months_due"] = member.months_due()
    response["membership"] = member.type

    return response

def _stats_for_month(year, month):
    # TODO: export this to the config
    money_required = 4300
    money_paid = 0
    mts = models.MemberTransfer.query.filter_by(year=year, month=month).\
        join(models.MemberTransfer.transfer).all()
    for mt in mts:
        amount_all = mt.transfer.amount
        amount = amount_all / len(mt.transfer.member_transfers)
        money_paid += amount

    return money_required, money_paid/100

@_public_api_method("month/<year>/<month>")
def api_month(year=None, month=None):
    money_required, money_paid = _stats_for_month(year, month)
    return dict(required=money_required, paid=money_paid)

@_public_api_method("mana")
def api_manamana(year=None, month=None):
    """To-odee doo-dee-doo!"""
    now = datetime.datetime.now()
    money_required, money_paid = _stats_for_month(now.year, now.month)
    return dict(required=money_required, paid=money_paid)

@_public_api_method("months_due/<membername>")
def api_months_due(membername):
    member = models.Member.query.filter_by(username=membername).first()
    if not member:
        return False
    year, month = member.get_last_paid()
    if not year:
        return False
    now = datetime.datetime.now()
    then_timestamp = year * 12 + (month-1)
    now_timestamp = now.year * 12 + (now.month-1)
    return now_timestamp - then_timestamp