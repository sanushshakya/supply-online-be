# Use the official Nginx image as the base image
FROM suzikc/nginx-server-with-certbot

RUN apt-get update

# Set the working directory
WORKDIR /usr/src/app

# Create a directory to store SSL certificates
RUN mkdir -p /usr/src/app/certs

# Copy Nginx configuration files
COPY nginx.conf /etc/nginx/nginx.conf

# Copy a shell script for SSL certificate renewal
COPY renew_certificates.sh /usr/src/app/renew_certificates.sh

# Make the shell script executable
RUN chmod +x /usr/src/app/renew_certificates.sh

# Specify entrypoint script
COPY entrypoint.sh /usr/src/app/entrypoint.sh
RUN chmod +x /usr/src/app/entrypoint.sh
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]

# Expose ports
EXPOSE 80
EXPOSE 443
