import socket,threading,time,statistics,json,struct

def run(nodelay):
    server=socket.socket(socket.AF_INET,socket.SOCK_STREAM,132)
    server.bind(("127.0.0.1",0));server.listen(1)
    received=[]
    def receive():
        peer,_=server.accept();peer.settimeout(5)
        while len(received)<30:
            message=peer.recv(4096)
            if not message:break
            received.append((struct.unpack("!I",message[:4])[0],time.monotonic_ns()))
        peer.close()
    worker=threading.Thread(target=receive);worker.start()
    sender=socket.socket(socket.AF_INET,socket.SOCK_STREAM,132)
    sender.setsockopt(132,3,int(nodelay));sender.connect(server.getsockname())
    start=time.monotonic()
    for i in range(30):
        time.sleep(max(0,start+i*.1-time.monotonic()))
        sender.sendall(struct.pack("!I",i)+b"m"*196)
    worker.join(5);sender.close();server.close()
    deltas=[(b[1]-a[1])/1e6 for a,b in zip(received,received[1:])]
    return {"nodelay":nodelay,"count":len(received),"min_ms":min(deltas),"median_ms":statistics.median(deltas),"max_ms":max(deltas),"intervals_ms":deltas}
print(json.dumps([run(False),run(True)],indent=2))
