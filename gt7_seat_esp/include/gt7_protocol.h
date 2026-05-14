#ifndef GT7_PROTOCOL_H
#define GT7_PROTOCOL_H

#include <Arduino.h>

#include "gt7_types.h"

namespace gt7
{
class FrameParser
{
public:
  void push(const uint8_t *data, size_t length);
  bool pop(Frame &out);

private:
  static constexpr size_t kHeaderSize = 12;

  uint8_t buffer_[config::kMaxFrameSize] = {};
  size_t buffer_len_ = 0;

  uint16_t readU16(size_t offset) const;
  void dropPrefix(size_t count);
};

void sendFrame(HardwareSerial &serial,
               uint16_t &next_seq,
               FrameType type,
               uint16_t device_id,
               const uint8_t *payload,
               uint16_t payload_len,
               uint8_t flags = 0);
void sendPing(HardwareSerial &serial, uint16_t &next_seq, uint16_t device_id);
void sendPong(HardwareSerial &serial, uint16_t &next_seq, uint16_t device_id);
void sendBindAck(HardwareSerial &serial, uint16_t &next_seq, uint16_t device_id, const char *ps5_ip);
}  // namespace gt7

#endif  // GT7_PROTOCOL_H
