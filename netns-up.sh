#!/bin/bash
# WireGuard in isolated netns "sfvpn" — only processes launched inside it use the VPN.
# SSH / Grace / other services stay on the direct route.
set -e

NS=sfvpn
WG=wgsf
ADDR=10.14.0.2/16
DNS1=162.252.172.57
DNS2=149.154.159.92

# Clean any prior state
ip netns del $NS 2>/dev/null || true
ip link del $WG 2>/dev/null || true

# Create namespace
ip netns add $NS
ip -n $NS link set lo up

# Create wg interface in ROOT ns (so its UDP socket lives here → egress via direct route)
ip link add $WG type wireguard
wg setconf $WG /root/meta-register/wg-nyc.conf

# Move the interface into the namespace
ip link set $WG netns $NS

# Configure inside the namespace
ip -n $NS addr add $ADDR dev $WG
ip -n $NS link set $WG up
ip -n $NS route add default dev $WG

# Per-namespace DNS
mkdir -p /etc/netns/$NS
printf "nameserver %s\nnameserver %s\n" "$DNS1" "$DNS2" > /etc/netns/$NS/resolv.conf

echo "netns $NS up. Verifying exit IP..."
ip netns exec $NS curl -s --max-time 20 https://ipinfo.io/json | grep -E '"ip"|"city"|"country"' || echo "IP check failed"
