# housefly.vome.io

The project page: a mix of write-up, method and install instructions.

`index.html` is self-contained — no build step, no assets, no JavaScript. Edit
it and copy it up:

```bash
sudo cp site/index.html /var/www/housefly/index.html
```

## How it is served

An nginx vhost at `/etc/nginx/sites-available/housefly.vome.io.conf`, static
root `/var/www/housefly`, enabled by the usual symlink into `sites-enabled`.
DNS needs nothing: `*.vome.io` already resolves to the host.

TLS is issued separately, following the same pattern as every other vhost on
that box:

```bash
sudo certbot --nginx -d housefly.vome.io --agree-tos --redirect -m <you@example.com>
```

Certbot edits the vhost in place to add the 443 server block and the redirect,
so re-copying this file over it afterwards would undo that. Edit
`/etc/nginx/sites-available/housefly.vome.io.conf` directly if you need to
change the server config after the certificate exists.
