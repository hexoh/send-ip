from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# 存储最后接收到的IP地址
last_ip = None

@app.route('/')
def index():
    return render_template('index.html', ip=last_ip)

@app.route('/receive_ip', methods=['POST'])
def receive_ip():
    global last_ip
    data = request.json
    last_ip = data.get('ip_address')
    return jsonify(success=True)

if __name__ == '__main__':
    app.run(debug=False)
