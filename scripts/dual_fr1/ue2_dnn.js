// Run using mongosh. Default: read-only check. Actions: apply, rollback.
// Rename only UE2's unique SST-1 IPv4 session; preserve authentication and QoS.
const action = process.env.SUBNET_ACTION || "check";
if (!["check", "apply", "rollback"].includes(action)) throw new Error("Invalid action");
const subscribers = db.getSiblingDB("open5gs").subscribers;
const from = action === "rollback" ? "internet2" : "internet";
const to = action === "rollback" ? "internet" : "internet2";

function readSession(imsi) {
  const rows = subscribers.find({imsi}, {
    imsi: 1, "slice.sst": 1, "slice.session.name": 1,
    "slice.session.type": 1, "slice.session.ue": 1
  }).toArray();
  if (rows.length !== 1) throw new Error(imsi + ": expected exactly one existing subscriber");
  const found = [];
  (rows[0].slice || []).forEach((slice, s) => {
    (slice.session || []).forEach((session, p) => {
      if (slice.sst === 1 && ["internet", "internet2"].includes(session.name))
        found.push({s, p, session});
    });
  });
  if (found.length !== 1 || found[0].session.type !== 1)
    throw new Error(imsi + ": expected one SST-1 internet/internet2 IPv4 session");
  return {id: rows[0]._id, ...found[0]};
}

const ue1 = readSession("001010000000101");
if (ue1.session.name !== "internet") throw new Error("UE1 must retain internet");
const ue2 = readSession("001010000000102");
if (ue2.session.ue && Object.values(ue2.session.ue).some(value => value))
  throw new Error("UE2 has a static UE address; review it before changing pools");
print("UE1: internet / IPv4; UE2: " + ue2.session.name + " / IPv4");
if (action !== "check" && ue2.session.name !== to) {
  const field = "slice." + ue2.s + ".session." + ue2.p + ".name";
  const filter = {_id: ue2.id, imsi: "001010000000102", [field]: from};
  filter["slice." + ue2.s + ".sst"] = 1;
  filter["slice." + ue2.s + ".session." + ue2.p + ".type"] = 1;
  const result = subscribers.updateOne(filter, {$set: {[field]: to}});
  if (result.matchedCount !== 1 || result.modifiedCount !== 1)
    throw new Error("UE2 changed concurrently; stop and inspect");
  print("UE2 DNN changed: " + from + " -> " + to);
} else if (action !== "check") {
  print("UE2 already uses " + to + "; no write needed");
}
