# Version 2 application message examples

Radio scope: these October 26 captures used direct n78 links with DU2 at
20 MHz. Their values and provenance are retained unchanged. See the
[current design](../../project_design_and_progress.md) for DU1 3660 MHz / 20 MHz,
DU2 3600-MHz logical interface / 40 MHz and its current Pi-Radio 9250-MHz OTA path.
The version-2 message format is unchanged by that radio-profile update.

The `client-*.json` files are illustrative requests. Supply your own `app_id`, request IDs, current exact radio keys if used, and the subscription ID returned by registration. Use only one register example per connection.

The `server-*.json` files are complete server frames extracted from the successful six-minute live dummy experiment on October 26, 2026. They retain the captured app ID `dual-ue-dummy`, broker instance, subscription, clocks, and KPM values. They do not represent responses to a newly run client request. The two KPM examples are independent samples from their respective paths.

Files are indented for reading. On the socket, serialize each object as one compact JSON line plus LF. The files omit dummy-added observation timestamps; [provenance.json](provenance.json) identifies their source receipt lines, hashes, and removed fields.

| Client request | Corresponding captured server message |
| --- | --- |
| [Register all links](client-register.json) or [register exact link](client-register-exact.json) | [Registration success](server-registration.json) |
| [Ping](client-ping.json) | [Pong](server-pong.json) |
| [Unregister](client-unregister.json) | [Unregistration success](server-unregistration.json) |
| Unsolicited push | [DU1 KPM](server-kpm-du1.json), [DU2 KPM](server-kpm-du2.json), [binding state](server-binding-state.json) |

The captured registration uses the all-links filter; it is not an exact-filter acknowledgement. Captured request IDs can differ from the illustrative requests, so a live client must correlate the IDs it actually sends.

See the [interface definition](../README.md) for required fields and lifecycle behavior.
