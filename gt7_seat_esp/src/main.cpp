#include <Arduino.h>

constexpr uint8_t kMagic0 = 'G';
constexpr uint8_t kMagic1 = '7';
constexpr uint8_t kProtocolVersion = 1;
constexpr uint32_t kBaudRate = 115200;
constexpr uint32_t kPingIntervalMs = 1000;
constexpr uint32_t kLinkTimeoutMs = 2500;
constexpr uint32_t kTelemetryTimeoutMs = 2500;
constexpr size_t kMaxPayloadSize = 96;
constexpr size_t kMaxFrameSize = 128;

#ifndef GT7_DEVICE_ID
#define GT7_DEVICE_ID 1
#endif

#ifndef GT7_STATUS_LED_PIN
#define GT7_STATUS_LED_PIN 2
#endif

enum class FrameType : uint8_t {
  Ping = 1,
  Pong = 2,
  Telemetry = 3,
  Bind = 4,
  Event = 5,
  Ack = 6,
};

struct TelemetryState {
  float car_speed = 0.0f;
  float engine_rpm = 0.0f;
  int8_t current_gear = -1;
  uint8_t throttle = 0;
  uint8_t brake = 0;
  bool in_race = false;
  float turbo_boost = 0.0f;
  float velocity_x = 0.0f;
  float velocity_y = 0.0f;
  float velocity_z = 0.0f;
  int16_t lap_count = -1;
  int16_t cars_in_race = -1;
  int32_t best_lap_time = -1;
  int32_t last_lap_time = -1;
};

struct Frame {
  FrameType type = FrameType::Ping;
  uint8_t flags = 0;
  uint16_t seq = 0;
  uint16_t device_id = 0;
  uint8_t payload[kMaxPayloadSize];
  uint16_t payload_len = 0;
};

class FrameParser {
 public:
  void push(const uint8_t* data, size_t length) {
    for (size_t i = 0; i < length; ++i) {
      if (buffer_len_ < kMaxFrameSize) {
        buffer_[buffer_len_++] = data[i];
      } else {
        drop_prefix(1);
        buffer_[buffer_len_++] = data[i];
      }
    }
  }

  bool pop(Frame& out) {
    while (buffer_len_ >= kHeaderSize) {
      if (buffer_[0] != kMagic0 || buffer_[1] != kMagic1) {
        drop_prefix(1);
        continue;
      }

      const uint8_t version = buffer_[2];
      if (version != kProtocolVersion) {
        drop_prefix(kHeaderSize);
        continue;
      }

      const uint16_t payload_len = read_u16(10);
      const size_t frame_len = kHeaderSize + payload_len;
      if (payload_len > kMaxPayloadSize) {
        drop_prefix(2);
        continue;
      }
      if (buffer_len_ < frame_len) {
        return false;
      }

      out.type = static_cast<FrameType>(buffer_[3]);
      out.flags = buffer_[4];
      out.seq = read_u16(6);
      out.device_id = read_u16(8);
      out.payload_len = payload_len;
      if (payload_len > 0) {
        memcpy(out.payload, buffer_ + kHeaderSize, payload_len);
      }
      drop_prefix(frame_len);
      return true;
    }

    return false;
  }

 private:
  static constexpr size_t kHeaderSize = 12;
  uint8_t buffer_[kMaxFrameSize];
  size_t buffer_len_ = 0;

  uint16_t read_u16(size_t offset) const {
    return static_cast<uint16_t>(buffer_[offset]) |
           static_cast<uint16_t>(buffer_[offset + 1]) << 8;
  }

  void drop_prefix(size_t count) {
    if (count >= buffer_len_) {
      buffer_len_ = 0;
      return;
    }
    memmove(buffer_, buffer_ + count, buffer_len_ - count);
    buffer_len_ -= count;
  }
};

TelemetryState telemetry_state;
FrameParser parser;

uint16_t next_seq = 1;
uint32_t last_ping_sent_ms = 0;
uint32_t last_pc_seen_ms = 0;
uint32_t last_telemetry_rx_ms = 0;
uint32_t last_ack_ms = 0;
uint32_t last_status_toggle_ms = 0;
bool status_led_on = false;
bool has_binding = false;
char bound_ps5_ip[16] = {0};

void write_u16(uint8_t* target, uint16_t value) {
  target[0] = static_cast<uint8_t>(value & 0xFF);
  target[1] = static_cast<uint8_t>((value >> 8) & 0xFF);
}

void write_u32(uint8_t* target, uint32_t value) {
  target[0] = static_cast<uint8_t>(value & 0xFF);
  target[1] = static_cast<uint8_t>((value >> 8) & 0xFF);
  target[2] = static_cast<uint8_t>((value >> 16) & 0xFF);
  target[3] = static_cast<uint8_t>((value >> 24) & 0xFF);
}

void send_frame(FrameType type, uint16_t device_id, const uint8_t* payload, uint16_t payload_len, uint8_t flags = 0) {
  uint8_t header[12];
  header[0] = kMagic0;
  header[1] = kMagic1;
  header[2] = kProtocolVersion;
  header[3] = static_cast<uint8_t>(type);
  header[4] = flags;
  header[5] = 0;
  write_u16(header + 6, next_seq++);
  write_u16(header + 8, device_id);
  write_u16(header + 10, payload_len);

  Serial.write(header, sizeof(header));
  if (payload_len > 0) {
    Serial.write(payload, payload_len);
  }
}

void send_ping() {
  send_frame(FrameType::Ping, GT7_DEVICE_ID, nullptr, 0);
}

void send_pong(uint16_t device_id) {
  send_frame(FrameType::Pong, device_id, nullptr, 0);
}

void send_bind_ack(uint16_t device_id, const char* ps5_ip) {
  uint8_t payload[4];
  IPAddress ip;
  if (ip.fromString(ps5_ip)) {
    payload[0] = ip[0];
    payload[1] = ip[1];
    payload[2] = ip[2];
    payload[3] = ip[3];
    send_frame(FrameType::Ack, device_id, payload, sizeof(payload));
    return;
  }
  send_frame(FrameType::Ack, device_id, nullptr, 0);
}

void handle_ping(const Frame& frame) {
  last_pc_seen_ms = millis();
  send_pong(frame.device_id);
}

void handle_pong(const Frame& frame) {
  (void)frame;
  last_pc_seen_ms = millis();
}

void handle_bind(const Frame& frame) {
  last_pc_seen_ms = millis();
  if (frame.payload_len >= 4) {
    IPAddress ip(frame.payload[0], frame.payload[1], frame.payload[2], frame.payload[3]);
    String ip_text = ip.toString();
    ip_text.toCharArray(bound_ps5_ip, sizeof(bound_ps5_ip));
    has_binding = true;
    send_bind_ack(frame.device_id, bound_ps5_ip);
  } else {
    has_binding = false;
    bound_ps5_ip[0] = '\0';
    send_bind_ack(frame.device_id, "");
  }
}

void handle_telemetry(const Frame& frame) {
  last_pc_seen_ms = millis();
  last_telemetry_rx_ms = millis();
  if (frame.payload_len < 40) {
    return;
  }

  const uint8_t* p = frame.payload;
  auto read_f32 = [&](size_t offset) -> float {
    float value;
    memcpy(&value, p + offset, sizeof(float));
    return value;
  };
  auto read_i16 = [&](size_t offset) -> int16_t {
    int16_t value;
    memcpy(&value, p + offset, sizeof(int16_t));
    return value;
  };
  auto read_i32 = [&](size_t offset) -> int32_t {
    int32_t value;
    memcpy(&value, p + offset, sizeof(int32_t));
    return value;
  };

  telemetry_state.car_speed = read_f32(0);
  telemetry_state.engine_rpm = read_f32(4);
  telemetry_state.current_gear = static_cast<int8_t>(p[8]);
  telemetry_state.throttle = p[9];
  telemetry_state.brake = p[10];
  telemetry_state.in_race = p[11] != 0;
  telemetry_state.turbo_boost = read_f32(12);
  telemetry_state.velocity_x = read_f32(16);
  telemetry_state.velocity_y = read_f32(20);
  telemetry_state.velocity_z = read_f32(24);
  telemetry_state.lap_count = read_i16(28);
  telemetry_state.cars_in_race = read_i16(30);
  telemetry_state.best_lap_time = read_i32(32);
  telemetry_state.last_lap_time = read_i32(36);

  (void)frame;
}

void handle_frame(const Frame& frame) {
  switch (frame.type) {
    case FrameType::Ping:
      handle_ping(frame);
      break;
    case FrameType::Pong:
      handle_pong(frame);
      break;
    case FrameType::Bind:
      handle_bind(frame);
      break;
    case FrameType::Telemetry:
      handle_telemetry(frame);
      break;
    default:
      break;
  }
}

bool link_is_healthy() {
  const uint32_t now = millis();
  return (now - last_pc_seen_ms) <= kLinkTimeoutMs ||
         (now - last_telemetry_rx_ms) <= kTelemetryTimeoutMs;
}

void update_status_led() {
  const uint32_t now = millis();
  const bool healthy = link_is_healthy();
  const bool timed_out = (now - last_pc_seen_ms) > kLinkTimeoutMs;

  if (healthy) {
    digitalWrite(GT7_STATUS_LED_PIN, LOW);
    status_led_on = false;
    return;
  }

  if (timed_out && (now - last_status_toggle_ms) >= 250) {
    status_led_on = !status_led_on;
    digitalWrite(GT7_STATUS_LED_PIN, status_led_on ? HIGH : LOW);
    last_status_toggle_ms = now;
  }
}

void poll_serial() {
  while (Serial.available() > 0) {
    uint8_t byte = static_cast<uint8_t>(Serial.read());
    parser.push(&byte, 1);
  }

  Frame frame;
  while (parser.pop(frame)) {
    handle_frame(frame);
  }
}

void send_periodic_ping() {
  const uint32_t now = millis();
  if (now - last_ping_sent_ms >= kPingIntervalMs) {
    send_ping();
    last_ping_sent_ms = now;
  }
}

void setup() {
  pinMode(GT7_STATUS_LED_PIN, OUTPUT);
  digitalWrite(GT7_STATUS_LED_PIN, LOW);
  Serial.begin(kBaudRate);
  Serial.setTimeout(0);
  delay(300);
  send_ping();
  last_ping_sent_ms = millis();
}

void loop() {
  poll_serial();
  send_periodic_ping();
  update_status_led();
  delay(5);
}