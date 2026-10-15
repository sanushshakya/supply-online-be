#!/bin/bash

# Run Certbot to renew SSL certificates
certbot certonly --nginx --agree-tos --no-eff-email --register-unsafely-without-email -d m18foods.co.uk -d www.m18foods.co.uk

# Copy renewed certificates to the Nginx certs folder
cp /etc/letsencrypt/live/m18foods.co.uk/fullchain.pem /usr/src/app/certs/certificate.crt
cp /etc/letsencrypt/live/m18foods.co.uk/privkey.pem /usr/src/app/certs/private_key.key

# Restart Nginx to apply the new certificates
nginx -s reload
