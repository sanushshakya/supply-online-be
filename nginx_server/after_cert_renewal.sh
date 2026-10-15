# copy the renewed certificate files
cp /etc/letsencrypt/live/m18foods.co.uk/fullchain.pem /usr/src/app/certs/certificate.crt
cp /etc/letsencrypt/live/m18foods.co.uk/privkey.pem /usr/src/app/certs/private_key.key


# Reload nginx
nginx -s reload