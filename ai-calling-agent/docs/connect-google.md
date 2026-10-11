# Connecting Google (and why it comes after deployment)

The OAuth code is written and tested. What is missing is a **stable HTTPS
URL**, and that is a prerequisite rather than a detail: Google requires
every redirect URI to be registered in advance and matched exactly, with no
wildcards. A Cloudflare quick tunnel gets a new hostname every day or two,
so each rotation would mean editing the URI in Google Cloud Console, and
again in Meta, and again in Twilio.

The same URL unblocks four things at once, which is why it is worth doing
first:

| Provider | Needs |
|---|---|
| Google  | `/api/v1/email/mailbox/callback` |
| Meta    | `/api/v1/meta/callback`, `/api/v1/meta/webhook` |
| Twilio  | `/api/v1/webhooks/telephony/*`, `/api/v1/webhooks/messaging/*` |
| Razorpay | its own webhook endpoint |

## 1. Deploy the API

`render.yaml` in the repository root describes the whole stack. On
render.com choose **New → Blueprint** and point it at this repository. You
get `https://stockvala-api.onrender.com`, which does not change.

One caveat worth knowing before you pick a plan. The free tier sleeps after
fifteen minutes idle and takes about thirty seconds to wake. That is fine
for an OAuth callback, where the cost is a slow redirect nobody minds. It is
the wrong choice for telephony: Twilio abandons a webhook after roughly
fifteen seconds, so a call arriving at a sleeping service fails outright
rather than being delayed. Move the web service to **starter** before you
dial for real.

Then point the frontend at it:

```
VITE_API_BASE_URL=https://stockvala-api.onrender.com/api/v1
```

## 2. Create the Google OAuth client

In [console.cloud.google.com](https://console.cloud.google.com):

1. Create a project.
2. **APIs & Services → Library → Gmail API → Enable.** Without this the
   token is issued and every send returns 403, which reads like a
   permissions bug rather than a missing API.
3. **OAuth consent screen** → External. Fill in the app name, support email
   and a privacy policy URL. Add the scope
   `https://www.googleapis.com/auth/gmail.send` — only that one. It cannot
   read a mailbox, which is both the honest thing to ask for and the
   difference between a light review and a heavy one.
4. **Credentials → Create credentials → OAuth client ID → Web application.**
   Authorised redirect URI:

   ```
   https://stockvala-api.onrender.com/api/v1/email/mailbox/callback
   ```

5. Put the client id and secret into the Render dashboard as
   `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

## 3. Testing mode, and what it costs to leave it

A new consent screen starts in **Testing**. Add up to 100 Google accounts
under *Test users* and they can connect immediately, with no review. For
most pilots that is enough, and it works the day you set it up.

Going past 100 means publishing, and `gmail.send` is a **restricted scope**.
Google requires verification, and restricted scopes additionally require a
CASA security assessment by a third-party auditor. It takes weeks and the
assessment is not always free. Plan for it rather than discovering it on
the day you want your 101st customer.

If that becomes the blocker, the alternative is Amazon SES behind the
existing SMTP adapter: roughly $0.10 per thousand emails, no per-user
consent, no review, and no daily cap. The code already supports it —
`EMAIL_PROVIDER=smtp` and credentials in provider settings.

## 4. Daily limits

These are Google's, not ours, and exceeding one suspends that mailbox for
twenty-four hours — which is why a send is refused at the ceiling rather
than attempted.

| Account | Per day |
|---|---|
| Personal Gmail | 500 |
| Google Workspace | 2,000 |
| Outlook | 300 |

At those numbers this is follow-up email, not bulk marketing. A list of ten
thousand needs SES.

## 5. Microsoft, if you want Outlook too

Azure portal → App registrations → New. Redirect URI is the same path.
Delegated permission `Mail.Send`, and `offline_access` so a refresh token is
issued. Set `MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET`.

Microsoft does not treat `Mail.Send` as restricted, so there is no
equivalent of Google's assessment.
