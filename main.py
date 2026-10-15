"""Cloud Monitoring (Pub/Sub) -> Slack Block Kit 整形通知"""
import base64
import json
import os

import functions_framework
import requests

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# Cloud Monitoring の severity -> (絵文字, 色)
SEVERITY_STYLE = {
    "CRITICAL": ("🔴", "#d93025"),
    "ERROR": ("🟠", "#e8710a"),
    "WARNING": ("🟡", "#f9ab00"),
}
DEFAULT_STYLE = ("🔔", "#5f6368")
RESOLVED_STYLE = ("✅", "#188038")


def _short(text, limit=2900):
    """Slack の section text は 3000 文字制限があるため切り詰める。"""
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_payload(data: dict) -> dict:
    inc = data["incident"]
    state = inc.get("state", "open")
    severity = (inc.get("severity") or "").upper()

    if state == "closed":
        emoji, color = RESOLVED_STYLE
        status_label = "解決"
    else:
        emoji, color = SEVERITY_STYLE.get(severity, DEFAULT_STYLE)
        status_label = "発生中"

    title = f"{emoji} [{status_label}] {inc.get('policy_name', 'Unknown policy')}"

    resource_name = (
        inc.get("resource_display_name")
        or inc.get("resource_name")
        or (inc.get("resource", {}) or {}).get("labels", {}).get("project_id", "-")
    )
    project_id = (inc.get("scoping_project_id")
                  or (inc.get("resource", {}) or {}).get("labels", {}).get("project_id", "-"))

    fields = [
        {"type": "mrkdwn", "text": f"*重大度*\n{severity or '-'}"},
        {"type": "mrkdwn", "text": f"*プロジェクト*\n{project_id}"},
        {"type": "mrkdwn", "text": f"*リソース*\n{resource_name}"},
        {"type": "mrkdwn", "text": f"*条件*\n{inc.get('condition_name', '-')}"},
    ]
    if inc.get("observed_value") not in (None, ""):
        fields.append({"type": "mrkdwn", "text": f"*観測値*\n{inc['observed_value']}"})
    if inc.get("threshold_value") not in (None, ""):
        fields.append({"type": "mrkdwn", "text": f"*しきい値*\n{inc['threshold_value']}"})

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": _short(title, 150)}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _short(inc.get("summary", ""))}},
        {"type": "section", "fields": fields},
    ]

    # アラートポリシーの Documentation（Runbook 等）があれば表示
    doc = (inc.get("documentation") or {}).get("content")
    if doc and state != "closed":
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": _short(f"*対応メモ*\n{doc}")}})

    if inc.get("url"):
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "インシデントを開く"},
                "url": inc["url"],
                **({"style": "danger"} if state != "closed" and severity == "CRITICAL" else {}),
            }],
        })

    # attachments + color で左端にカラーバーを出す
    return {
        "text": title,  # 通知プレビュー用フォールバック
        "attachments": [{"color": color, "blocks": blocks}],
    }


@functions_framework.cloud_event
def notify(cloud_event):
    raw = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    data = json.loads(raw)
    payload = build_payload(data)
    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    resp.raise_for_status()  # 失敗時は例外 -> Pub/Sub が再配信
