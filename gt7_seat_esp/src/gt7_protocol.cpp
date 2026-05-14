#include "gt7_protocol.h"

#include <IPAddress.h>
#include <string.h>

namespace gt7
{
namespace
{
void writeU16(uint8_t *target, uint16_t value)
{
  target[0] = static_cast<uint8_t>(value & 0xFF);
  target[1] = static_cast<uint8_t>((value >> 8) & 0xFF);
}
}  // namespace

void FrameParser::push(const uint8_t *data, size_t length)
{
  for (size_t i = 0; i < length; ++i)
  {
    if (buffer_len_ < config::kMaxFrameSize)
    {
      buffer_[buffer_len_++] = data[i];
    }
    else
    {
      dropPrefix(1);
      buffer_[buffer_len_++] = data[i];
    }
  }
}

bool FrameParser::pop(Frame &out)
{
  while (buffer_len_ >= kHeaderSize)
  {
    if (buffer_[0] != config::kMagic0 || buffer_[1] != config::kMagic1)
    {
      dropPrefix(1);
      continue;
    }

    if (buffer_[2] != config::kProtocolVersion)
    {
      dropPrefix(kHeaderSize);
      continue;
    }

    const uint16_t payload_len = readU16(10);
    const size_t frame_len = kHeaderSize + payload_len;
    if (payload_len > config::kMaxPayloadSize)
    {
      dropPrefix(2);
      continue;
    }
    if (buffer_len_ < frame_len)
    {
      return false;
    }

    out.type = static_cast<FrameType>(buffer_[3]);
    out.flags = buffer_[4];
    out.seq = readU16(6);
    out.device_id = readU16(8);
    out.payload_len = payload_len;
    if (payload_len > 0)
    {
      memcpy(out.payload, buffer_ + kHeaderSize, payload_len);
    }
    dropPrefix(frame_len);
    return true;
  }

  return false;
}

uint16_t FrameParser::readU16(size_t offset) const
{
  return static_cast<uint16_t>(buffer_[offset]) |
         static_cast<uint16_t>(buffer_[offset + 1]) << 8;
}

void FrameParser::dropPrefix(size_t count)
{
  if (count >= buffer_len_)
  {
    buffer_len_ = 0;
    return;
  }

  memmove(buffer_, buffer_ + count, buffer_len_ - count);
  buffer_len_ -= count;
}

void sendFrame(HardwareSerial &serial,
               uint16_t &next_seq,
               FrameType type,
               uint16_t device_id,
               const uint8_t *payload,
               uint16_t payload_len,
               uint8_t flags)
{
  uint8_t header[12];
  header[0] = config::kMagic0;
  header[1] = config::kMagic1;
  header[2] = config::kProtocolVersion;
  header[3] = static_cast<uint8_t>(type);
  header[4] = flags;
  header[5] = 0;
  writeU16(header + 6, next_seq++);
  writeU16(header + 8, device_id);
  writeU16(header + 10, payload_len);

  serial.write(header, sizeof(header));
  if (payload_len > 0)
  {
    serial.write(payload, payload_len);
  }
}

void sendPing(HardwareSerial &serial, uint16_t &next_seq, uint16_t device_id)
{
  sendFrame(serial, next_seq, FrameType::Ping, device_id, nullptr, 0);
}

void sendPong(HardwareSerial &serial, uint16_t &next_seq, uint16_t device_id)
{
  sendFrame(serial, next_seq, FrameType::Pong, device_id, nullptr, 0);
}

void sendBindAck(HardwareSerial &serial, uint16_t &next_seq, uint16_t device_id, const char *ps5_ip)
{
  uint8_t payload[4];
  IPAddress ip;
  if (ip.fromString(ps5_ip))
  {
    payload[0] = ip[0];
    payload[1] = ip[1];
    payload[2] = ip[2];
    payload[3] = ip[3];
    sendFrame(serial, next_seq, FrameType::Ack, device_id, payload, sizeof(payload));
    return;
  }

  sendFrame(serial, next_seq, FrameType::Ack, device_id, nullptr, 0);
}
}  // namespace gt7
