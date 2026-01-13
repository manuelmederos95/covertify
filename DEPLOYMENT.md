# Deploying Covertify to Railway.app

## Step-by-Step Deployment Guide

### 1. Prepare Your Repository

First, initialize a git repository and push to GitHub:

```bash
cd /Users/manuelmederos/Desktop/Covertify

# Initialize git (if not already done)
git init

# Add all files
git add .

# Commit
git commit -m "Initial commit - Covertify deployment"

# Create a new repository on GitHub (https://github.com/new)
# Then push to GitHub:
git remote add origin https://github.com/YOUR_USERNAME/covertify.git
git branch -M main
git push -u origin main
```

### 2. Deploy to Railway

1. **Go to Railway.app**
   - Visit https://railway.app/
   - Click "Start a New Project"
   - Login with GitHub

2. **Deploy from GitHub**
   - Click "Deploy from GitHub repo"
   - Select your `covertify` repository
   - Railway will automatically detect it's a Python app

3. **Set Environment Variables**
   - Go to your project dashboard
   - Click on "Variables" tab
   - Add the following environment variable:
     ```
     RUNWAYML_API_SECRET=key_2542f0ea77aa972ca8219c227d03ea77454d87911235909a472c0779f79b26f66278467b790520ffa21baed42fed9d78b80540ccbbd5ecc2645ad96e315bfbb4
     ```

4. **Wait for Deployment**
   - Railway will automatically build and deploy your app
   - This takes 3-5 minutes
   - FFmpeg is automatically included via nixpacks.toml

5. **Get Your Railway URL**
   - Once deployed, Railway will give you a URL like: `https://your-app.up.railway.app`
   - Test it to make sure it works!

### 3. Connect Your Custom Domain (covertify.io)

1. **In Railway Dashboard**
   - Go to your project settings
   - Click "Custom Domain"
   - Enter: `covertify.io`
   - Railway will show you DNS records to add

2. **In Namecheap Dashboard**
   - Login to Namecheap
   - Go to Domain List > Manage for covertify.io
   - Click "Advanced DNS"
   - Add the DNS records Railway provided:
     - Type: `CNAME`
     - Host: `@` (or `www`)
     - Value: `your-app.up.railway.app`
     - TTL: Automatic

3. **Wait for DNS Propagation**
   - DNS changes can take 5 minutes to 24 hours
   - Usually it's ready in 10-30 minutes
   - Test by visiting https://covertify.io

### 4. Post-Deployment Checklist

- [ ] App is accessible at Railway URL
- [ ] Environment variables are set
- [ ] FFmpeg is working (upload test)
- [ ] Runway API generates videos successfully
- [ ] Custom domain is connected
- [ ] SSL certificate is active (Railway provides this automatically)

## Important Notes

### Free Tier Limits
- Railway free tier includes:
  - $5 credit per month
  - 500 hours of execution time
  - Sufficient for testing and light usage

### Monitoring
- Check Railway dashboard for logs
- Monitor usage to avoid exceeding free tier

### Scaling
If you need more resources:
- Upgrade to Railway Pro ($20/month)
- Or migrate to a VPS (DigitalOcean/Linode)

## Troubleshooting

### Build Fails
- Check Railway logs for errors
- Ensure all files are committed to git
- Verify requirements.txt is correct

### App Won't Start
- Check environment variables are set
- Look at Railway logs for Python errors
- Verify Gunicorn is starting properly

### FFmpeg Not Found
- The nixpacks.toml file should install it automatically
- If issues persist, check Railway build logs

### Domain Not Working
- Verify DNS records in Namecheap
- Use `dig covertify.io` to check DNS propagation
- Wait up to 24 hours for full propagation

## Support

For Railway-specific issues:
- Railway Docs: https://docs.railway.app/
- Railway Discord: https://discord.gg/railway

For Covertify issues:
- Check the logs in Railway dashboard
- Review app.py for error handling
