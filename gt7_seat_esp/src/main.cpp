#include <Arduino.h>

#include "seat_controller.h"

namespace
{
gt7::SeatController controller;
}

void setup()
{
  controller.setup();
}

void loop()
{
  controller.loop();
}
