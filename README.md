# UDR7 WireGuard speeds capped, turns out hardware AES is compiled out

Been chasing this for a while. Site-to-site WireGuard tunnel between a UDR7 at home and a
UCG-Fiber at a remote site, both on latest EA firmware. Tunnel speeds capped around 200 Mbps
no matter what I threw at it. SMB copies were brutal, iperf3 confirmed the bottleneck, and
none of the usual suspects panned out. Opened a support ticket and started digging.

## Ruling stuff out

First thing was making sure it was actually the tunnel and not something else in the path.
Ran iperf3 three ways:

- Outside the tunnel, direct WAN to WAN: full speed
- Inside the LAN to a local box: full speed  
- Through the WireGuard tunnel: ~200 Mbps and that's it

So definitely the tunnel. Then I tested IPsec and OpenVPN through the same devices because
why not. OpenVPN was awful as expected. IPsec hit the same ~200 Mbps ceiling though, which
was interesting. If both protocols cap at the same number that's not really a "WireGuard
is broken" problem, that's a "this device can't do crypto fast" problem.

## The loop detection thing

Had htop open during one of the tests and noticed this scrolling past at the top:

```
kernel: wireguard: wgsts1000: possible loop detected, dropping skb of size 65216
```

Repeated over and over during the iperf3 run. Large SKBs getting dropped, which lines up
perfectly with what I was seeing. Small stuff like DNS and pings was fine, but anything
that pushed real bandwidth fell apart. WireGuard's loop detection fires when it thinks
packets are being routed back into the same tunnel interface, which usually means the
endpoint IP somehow got a route pointing into the tunnel itself.

Pulled the kernel log entries, threw them in the support ticket. Rebooted after hours
(WFH household, can't just reboot the router whenever) and updated to the new 5.1.15
firmware that dropped the same day. After the reboot the loop errors stopped and speeds
went up to around 350 Mbps. Better, but still not the 700-800 Mbps people online claim
to get on the same hardware.

## CPU usage was telling

Watched htop during another iperf3 run after the reboot. All four cores loaded up to
75-95%. On a device with hardware AES acceleration that shouldn't happen for tunnel
traffic. The whole point of having `aes` and `pmull` in your CPU flags is so the crypto
work doesn't eat your general purpose CPU. So either the hardware acceleration wasn't
being used, or something else was burning CPU on every packet.

That's what sent me down the rabbit hole.

## Confirming the CPU actually has the instructions

```
Vendor:    Qualcomm
Model:     Kryo V2
CPU MHz:   1500
Flags:     fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid
```

`aes` and `pmull` are there. ARMv8 Crypto Extensions, exactly what you want for AES-GCM
acceleration. So the silicon is capable. Question is whether the kernel is actually using
it.

## Checking what crypto the kernel is using

```
name   : aes
driver : aes-generic

name   : gcm(aes)
driver : gcm_base(ctr(aes-generic),ghash-generic)

name   : ghash
driver : ghash-generic
```

Every driver is `*-generic`. That's pure software. You'd want to see `aes-ce`, `ghash-ce`,
or `aes-ce-blk`. The `-ce` suffix is for the ARM crypto extensions. None of those exist
anywhere in `/proc/crypto`.

So the kernel is doing every AES operation in software on a 1.5 GHz ARM core. That alone
would explain why throughput sucks.

## Maybe the modules just aren't loaded?

Looked for them:

```bash
find /lib/modules -name "aes-ce*" -o -name "ghash-ce*"
```

Nothing. Empty result. Okay, maybe they're built into the kernel directly rather than
shipped as loadable modules. Checked the kernel config:

```bash
zcat /proc/config.gz | grep -i "arm64_crypto"
```

And there it is:

```
# CONFIG_ARM64_CRYPTO is not set
```

The entire ARM64 crypto subsystem is disabled at compile time. Not just missing, not
failing to load, actively turned off when they built the kernel. That disables aes-ce,
ghash-ce, sha2-ce, chacha20-neon, the whole lot.

So the CPU has hardware AES instructions sitting right there, the kernel was built with
no way to use them, and as a result every WireGuard packet (and every IPsec packet, and
everything else that does AES) is getting encrypted in software at 1.5 GHz. That's the
whole story.

## Other stuff worth mentioning

While I was poking around:

- wireguard-tools is `v1.0.20210914`. Current stable is from Feb 2026. That build is
  almost 5 years old.
- Kernel is 5.4.213. Mainline 5.4 came out in November 2019. Most of the ARM crypto
  performance improvements landed in 5.10 and later.
- Base OS is Debian Bullseye, which is oldoldstable now. Two releases behind.
- OpenSSL benchmark on the device shows about 500 Mbps peak for aes-256-gcm with large
  blocks, in software. With CE enabled this hardware should comfortably double that.

None of those are the smoking gun by themselves but they paint the picture of a software
stack that hasn't been keeping up with the hardware.

## What I think is going on

The fix is a kernel rebuild with `CONFIG_ARM64_CRYPTO=y` and the relevant sub-options
(`CRYPTO_AES_ARM64_CE`, `CRYPTO_GHASH_ARM64_CE`, etc). That's not something I can do, it
has to come from Ubiquiti.

What's strange is that people online with the same hardware report 700-800 Mbps over
WireGuard, which is what you'd expect with CE enabled. So either it was enabled at some
point and got turned off, or there are different kernel builds out there for different
hardware revisions, or those people are running on different devices entirely. No idea
which.

Ticket is open with Ubiquiti, we'll see what they say. Hopefully someone in their kernel
team can flip the switch and ship a build. 
