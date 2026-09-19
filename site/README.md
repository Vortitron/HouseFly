# housefly.vome.io

The project page: a mix of write-up, method and install instructions.

`index.html` is self-contained — no build step, no assets, no JavaScript. Edit
it and copy it up:

```bash
sudo cp site/index.html /var/www/housefly/index.html
```

## The demo link

`/demo` is an nginx 302 to the hosted demo's guest sign-in, so the token is not
in the page source and rotating it is one line in one file rather than an edit
and a redeploy. A copy of the vhost lives here as
`nginx-housefly.vome.io.conf`, for reference only -- the live one is the file
under `/etc/nginx`, because certbot edits it in place.

The current link is a non-admin guest that **expires 2026-10-19**. To reissue:
create a new guest link for the demo instance with `dashboard: lovelace`, put it
in that `location = /demo` block, `nginx -t`, reload. Anyone who follows the
link is signed straight in as the Guest user, which is the point -- but it does
mean the link should only ever point at the demo instance and never at a real
house.

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
