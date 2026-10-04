import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("locahost", 5000))
    s.listen()
    print("Server is lisening")

    conn, addr = s.accept()
    with conn:
        print("Conneted by addr")
        while True:
            data = conn.recv(1024)
            if not data:
                break
            conn.sendall(data)