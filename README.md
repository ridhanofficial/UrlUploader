<h1 align="center">Telegram URL Uploader Bot with Premium Features</h1>

<p align="center">
  <a href="https://github.com/bisnuray/URLUploader/stargazers"><img src="https://img.shields.io/github/stars/bisnuray/URLUploader?color=blue&style=flat" alt="GitHub Repo stars"></a>
  <a href="https://github.com/bisnuray/URLUploader/issues"><img src="https://img.shields.io/github/issues/bisnuray/URLUploader" alt="GitHub issues"></a>
  <a href="https://github.com/bisnuray/URLUploader/pulls"><img src="https://img.shields.io/github/issues-pr/bisnuray/URLUploader" alt="GitHub pull requests"></a>
  <a href="https://github.com/bisnuray/URLUploader/graphs/contributors"><img src="https://img.shields.io/github/contributors/bisnuray/URLUploader?style=flat" alt="GitHub contributors"></a>
  <a href="https://github.com/bisnuray/URLUploader/network/members"><img src="https://img.shields.io/github/forks/bisnuray/URLUploader?style=flat" alt="GitHub forks"></a>
  <a href="https://github.com/bisnuray/URLUploader/blob/master/LICENSE"><img src="https://img.shields.io/github/license/bisnuray/URLUploader?style=flat" alt="GitHub license"></a>
</p>

<p align="center">
  <em>A Telegram bot that can download files from URLs and upload them to Telegram. Supports premium features for enhanced capabilities.</em>
</p>
<hr>

## ✨ Features

- 📥 Download files from direct URLs
- 📈 Premium enhanced features
- 📊 Upload Up to 4GB  
- ✏️ File renaming capability
- 📈 Progress tracking
- 📹 YouTube video download support

## Environment Variables

Create a `.env` file with the following variables:

```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
SESSION_STRING=your_session_string
OWNER_ID=your_telegram_id
```

## 🚀 Deploy to Heroku

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/YourUsername/URLUploader)

### Environment Variables Required

```
BOT_TOKEN - Get from @BotFather
API_ID - Get from my.telegram.org
API_HASH - Get from my.telegram.org
AUTH_USERS - Your Telegram ID
```

## Deployment to Heroku

1. Create a Heroku account if you don't have one
2. Install Heroku CLI
3. Login to Heroku:
   ```bash
   heroku login
   ```
4. Create a new Heroku app:
   ```bash
   heroku create your-app-name
   ```
5. Set the environment variables in Heroku dashboard or using CLI:
   ```bash
   heroku config:set API_ID=your_api_id
   heroku config:set API_HASH=your_api_hash
   heroku config:set BOT_TOKEN=your_bot_token
   heroku config:set SESSION_STRING=your_session_string
   heroku config:set OWNER_ID=your_telegram_id

   ```
6. Deploy to Heroku:
   ```bash
   git add .
   git commit -m "Ready for deployment"
   git push heroku master
   ```

## Commands

- `/start` - Start the bot
- `/premium` - Check premium status
- `/help` - Get help message

## Premium Features

- 📈 Increased file size limit (10GB)
- 🔄 More concurrent downloads (5)
- ⚡️ Priority processing
- 📞 Premium support

Contact the bot owner to get premium access.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For support, contact [@your_username](https://t.me/your_username)
