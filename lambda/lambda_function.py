from slack import WebClient
# from slack.errors import SlackApiError
import json, os
from collections import namedtuple

Paper = namedtuple("Paper", ["slackID", "filename", "doi", "pmid", "arXiv", "slackLink", "externalLink", "title", "md5",
                             "rating", "OSS", "field"], defaults=[""] * 10)

client = WebClient(token=os.environ['SLACK_VERIFICATION_TOKEN'])
apiurl = os.environ["SELF_API_URL"]

OK = {'statusCode': 200}

debug = lambda s: client.chat_postMessage(channel="paper-a-day_dev", text=s)


def handleFileEvent(data):
    file_id = data["file_id"]

    filedata = client.files_info(
        channel=data["channel_id"],
        file=file_id
    )["file"]

    filetype = filedata["filetype"]

    if filetype == "pdf" and data["type"] in ["file_created", "file_shared"]:
        msg = {
            "response_url": apiurl,
            "channel": data["channel_id"],
            "user": data["user_id"],
            "attachments": [
                {
                    "text": "Is this ({}) a paper you (<@{}>) read?".format(filedata["name"], data["user_id"]),
                    "fallback": "The office is now closed. [Closes window on your hands.]",
                    "callback_id": "read-paper",
                    "link_names": True,
                    "color": "#3AA3E3",
                    "attachment_type": "default",
                    "actions": [
                        {
                            "name": "yes",
                            "text": "Yes!",
                            "style": "danger",
                            "type": "button",
                            "value": file_id,
                            "confirm": {
                                "title": "Don't be a weasel.",
                                "text": "It's better to not accomplish your goals than to be a liar!",
                                "ok_text": "I PROMISE I READ IT!",
                                "dismiss_text": "I did not read it."
                            }
                        },
                        {
                            "name": "no",
                            "text": "No.",
                            "type": "button",
                            "value": "NO"
                        }
                    ]
                }
            ]
        }

        client.api_call("chat.postEphemeral", json=msg)
    return OK


def handleSlackEvent(data):
    if data["type"] in ["file_created", "file_shared"]:
        return handleFileEvent(data)
    raise Exception("No valid slack handler found ! Data: {}".format(data))


def getPaperInfo(body):
    filedata = client.files_info(
        channel=body["channel"]["id"],
        file=body["actions"][0]["value"]
    )["file"]

    return Paper(slackID=filedata["id"], filename=filedata["name"]), filedata


def logReadPaper(paper, user, channel, rawdata, anonSubmission):
    import boto3
    table = boto3.resource('dynamodb').Table('paper-a-day_papers')
    response = table.put_item(
        Item={
            'id': paper.slackID,
            'user': user,
            'channel': channel,
            'paper': paper.filename,
            'filedata': str(rawdata),
            'anonSubmission': anonSubmission
        }
    )
    return


def processHTTPHooks(user, paper):
    if user in ["uttmark"]:
        import requests

        requests.post(
           "https://maker.ifttt.com/trigger/slack_paper_upload/with/key/bNpead6Zfy1AhFv201SYXTq49RBnEgTQ-ILg-1_LiRW",
            data={"value1": paper.filename, "value2": "", "value3": ""})
        return "\nYou have a Beeminder account. Cute. I sent them a message."
    return ""


def handleDirectCall(body):
    from urllib import parse as urlparse
    body = urlparse.parse_qs(body)
    body = json.loads(body["payload"][0])
    if body["type"] == "interactive_message":
        try:
            client.api_call("chat.delete", json={"channel": body["channel"]["id"], "ts": body["message_ts"]})
        except Exception:
            pass
        if body["callback_id"] == "read-paper":
            if not body["actions"][0]["value"] == "NO":
                paper, rawdata = getPaperInfo(body)
                anonSubmission = body["channel"]["name"] == "directmessage"
                logReadPaper(paper, body["user"]["name"], body["channel"]["id"], rawdata, anonSubmission)
                httpNotices = processHTTPHooks(body["user"]["name"], paper)
                if not anonSubmission:
                    client.chat_postMessage(channel=body["channel"]["id"],
                                            text="{} just read {} :tada:".format(body["user"]["name"], paper.filename))
                return "Okay, I'll mark {} down as having read {}.".format(body["user"]["name"],
                                                                           paper.filename) + httpNotices
            else:
                return "Okay, I won't do anything then. We don't want another ... incident."
    elif body["type"] == "message_action" and body["callback_id"] =="shortcut-mark_paper_read":
        try:
            paper = Paper(slackID=body["message"]["files"][0]["id"], filename=body["message"]["files"][0]["name"])
            logReadPaper(paper, body["user"]["name"], body["channel"]["id"], body["message"]["files"], False)
            httpNotices = processHTTPHooks(body, paper)
        except KeyError:
            return OK
        client.chat_postMessage(channel=body["channel"]["id"],
                                text="{} just read {} :tada:".format(body["user"]["name"], paper.filename))
        return OK


def lambda_handler(event, context):
    """
    This function is the entry point on AWS Lambda
    (it's the first thing run!)

    :param event:
    :param context:
    :return:
    """
    # sometime slack will re-ping if we don't reply in time
    # return OK to let slack know we got the request and are working on it
    if 'X-Slack-Retry-Num' in event['headers']:
        slk_retry = event['headers']['X-Slack-Retry-Num']
        return 200
    if "body" in event.keys():
        try:
            if event["isBase64Encoded"]:
                import base64
                body = base64.b64decode(event["body"]).decode('utf-8')
            else:
                body = event["body"]
        except KeyError:
            try:
                body = event["body"]
            except KeyError:
                return {
                    'statusCode': 400,
                    'body': json.dumps("No body; invalid request"),
                    'event': event
                }
        finally:
            try:
                data = json.loads(body)["event"]
                if "user-agent" in event["headers"] and "Slackbot" in event["headers"]["user-agent"]:
                    return handleSlackEvent(data)
                else:
                    return handleDirectCall(body)
            except json.decoder.JSONDecodeError:
                return handleDirectCall(body)

    return {
        'statusCode': 200,
        'body': json.dumps('No actions were taken :('),
        'event': event
    }
