# Blog auto-publisher

Runs twice a day as a Render cron job. Promotes Sanity drafts whose `scheduledFor` has passed and whose review status is Auto, keeps the calendar's `publishedAt`, pings IndexNow, and warns the WhatsApp Ops group when fewer than 14 scheduled drafts remain. Secrets live in Render environment variables, never here. Set `PUBLISH_PAUSED=1` to pause.
