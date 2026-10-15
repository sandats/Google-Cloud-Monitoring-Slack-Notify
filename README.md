# Cloud Monitoring → Slack 整形通知

Cloud Monitoring のアラートを Pub/Sub 経由で受け取り、Slack の Block Kit で見やすく通知します。

```
Alert Policy → Pub/Sub 通知チャネル → Pub/Sub topic → Cloud Run functions → Slack Incoming Webhook
```

## 0. 変数

```bash
export PROJECT_ID=your-project
export REGION=asia-northeast1
export TOPIC=monitoring-alerts
export FUNC=monitoring-slack-notifier
gcloud config set project $PROJECT_ID
```

## 1. Slack Incoming Webhook を用意

Slack App を作成し、Incoming Webhooks を有効化して、通知先チャンネルの Webhook URL を発行します。

## 2. Webhook URL を Secret Manager に保存

```bash
gcloud services enable secretmanager.googleapis.com run.googleapis.com \
  cloudfunctions.googleapis.com eventarc.googleapis.com pubsub.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com

printf '%s' 'https://hooks.slack.com/services/XXX/YYY/ZZZ' | \
  gcloud secrets create slack-webhook-url --data-file=-
```

## 3. Pub/Sub トピック作成

```bash
gcloud pubsub topics create $TOPIC
```

## 4. 専用サービスアカウントを作成して Secret の閲覧権限を付与

```bash
gcloud iam service-accounts create sa-monitoring-slack --display-name="Monitoring Slack notifier"

gcloud secrets add-iam-policy-binding slack-webhook-url \
  --member="serviceAccount:sa-monitoring-slack@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## 5. デプロイ

```bash
gcloud functions deploy $FUNC \
  --gen2 \
  --region=$REGION \
  --runtime=python312 \
  --source=. \
  --entry-point=notify \
  --trigger-topic=$TOPIC \
  --service-account=sa-monitoring-slack@${PROJECT_ID}.iam.gserviceaccount.com \
  --set-secrets=SLACK_WEBHOOK_URL=slack-webhook-url:latest
```

## 6. Cloud Monitoring に通知チャネルを追加

1. Cloud Monitoring → Alerting → Edit notification channels → **Pub/Sub** → Add new
2. トピックに `monitoring-alerts` を指定して保存
3. 初回は Monitoring のサービスエージェントに Publisher 権限が必要です。画面の案内に従って付与してください（手動の場合）:

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
gcloud pubsub topics add-iam-policy-binding $TOPIC \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-monitoring-notification.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

4. 対象のアラートポリシーの通知チャネルに、この Pub/Sub チャネルを追加（既存の Slack チャネルは外す）

## 7. 動作確認

### ローカル（Slack に送らず JSON だけ確認）

```bash
python test_local.py
```

### 疎通確認（Pub/Sub に直接投げる）

```bash
gcloud pubsub topics publish $TOPIC --message="$(cat sample_alert.json)"
```

Slack に通知が届けば成功です。ログは以下で確認できます。

```bash
gcloud functions logs read $FUNC --gen2 --region=$REGION --limit=50
```

## メモ

- `documentation.content`（アラートポリシーの Documentation）は「対応メモ」として自動表示されます。Runbook のリンクを書いておくと便利です。
- Slack への POST が失敗すると例外になり、Pub/Sub が再配信します。
- Block Kit のレイアウトは `main.py` の `build_payload` を編集すれば変えられます。Slack の [Block Kit Builder](https://app.slack.com/block-kit-builder) でプレビューできます。
