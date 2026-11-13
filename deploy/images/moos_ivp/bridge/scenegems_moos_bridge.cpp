// The bridge between the MOOS-IvP component's server (moos_ivp_server.py) and the MOOSDB of a run.
//
// A MOOS client that takes tab-separated commands, one per line, on its standard input and
// answers every query with one line on its standard output (DRAIN with one line per value):
//
//   CLOCK <t>                         store t in the external clock file               -> OK
//   REG <var>                         register for var and keep its latest value       -> OK
//   QREG <var>                        register for var and keep every value in a queue -> OK
//   D <var> <double>                  post a double                                    (no answer)
//   S <var> <string>                  post a string                                    (no answer)
//   CONNECTED <timeout_ms>            wait for the connection to the MOOSDB            -> OK | TIMEOUT
//   WAITVAL <var> <min> <timeout_ms>  wait until var's double value is at least min    -> OK <count> | TIMEOUT <count>
//   GET <var>                         latest value of a registered var                 -> <count> <time> <D|S> <value>
//   DRAIN <var>                       the queued values of var since the last drain    -> <n>, then n lines of values
//   QUIT
//
// The clock file is the one libMOOS reads its time from (MOOS_EXTERNAL_CLOCK, the external clock
// of the pinned MOOS-IvP fork): the bridge is the process that owns MOOS time. It links libMOOS only.

#include "MOOS/libMOOS/Comms/MOOSAsyncCommClient.h"

#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <fcntl.h>
#include <iomanip>
#include <iostream>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <sys/mman.h>
#include <unistd.h>
#include <vector>

struct Latest {
  unsigned long count = 0;
  double time = 0;
  bool is_double = true;
  double number = 0;
  std::string text;
};

struct Bridge {
  MOOS::MOOSAsyncCommClient comms;
  std::mutex mutex;
  std::condition_variable changed;
  std::map<std::string, Latest> latest;
  std::map<std::string, std::vector<std::string>> queues;
  std::set<std::string> queued;
  std::vector<std::string> registered;
  bool connected = false;
};

static std::string single_line(std::string text) {
  for (char& character : text)
    if (character == '\n' || character == '\r' || character == '\t') character = ' ';
  return text;
}

static bool on_connect(void* param) {
  Bridge* bridge = static_cast<Bridge*>(param);
  std::lock_guard<std::mutex> lock(bridge->mutex);
  bridge->connected = true;
  for (const std::string& name : bridge->registered) bridge->comms.Register(name, 0);
  bridge->changed.notify_all();
  return true;
}

static bool on_mail(void* param) {
  Bridge* bridge = static_cast<Bridge*>(param);
  MOOSMSG_LIST mail;
  bridge->comms.Fetch(mail);
  std::lock_guard<std::mutex> lock(bridge->mutex);
  for (CMOOSMsg& message : mail) {
    const std::string name = message.GetKey();
    Latest& entry = bridge->latest[name];
    entry.count++;
    entry.time = message.GetTime();
    entry.is_double = message.IsDouble();
    if (entry.is_double)
      entry.number = message.GetDouble();
    else
      entry.text = single_line(message.GetString());
    if (bridge->queued.count(name)) {
      std::ostringstream value;
      value << std::setprecision(17);
      if (entry.is_double)
        value << entry.number;
      else
        value << entry.text;
      bridge->queues[name].push_back(value.str());
    }
  }
  bridge->changed.notify_all();
  return true;
}

static std::vector<std::string> split(const std::string& line) {
  std::vector<std::string> parts;
  std::string part;
  std::istringstream stream(line);
  while (std::getline(stream, part, '\t')) parts.push_back(part);
  return parts;
}

int main(int argc, char** argv) {
  if (argc < 5) {
    std::cerr << "usage: scenegems_moos_bridge <host> <port> <client name> <clock file>\n";
    return 2;
  }
  int file = open(argv[4], O_RDWR);
  void* map = file < 0 ? MAP_FAILED : mmap(nullptr, sizeof(double), PROT_READ | PROT_WRITE, MAP_SHARED, file, 0);
  if (map == MAP_FAILED) {
    std::cerr << "cannot map the clock file " << argv[4] << "\n";
    return 2;
  }
  close(file);
  volatile double* clock = static_cast<volatile double*>(map);

  Bridge bridge;
  bridge.comms.SetOnConnectCallBack(on_connect, &bridge);
  bridge.comms.SetOnMailCallBack(on_mail, &bridge);
  bridge.comms.SetQuiet(true);
  bridge.comms.Run(argv[1], std::atoi(argv[2]), argv[3]);

  std::cout << std::setprecision(17);
  std::string line;
  while (std::getline(std::cin, line)) {
    std::vector<std::string> parts = split(line);
    if (parts.empty()) continue;
    const std::string& op = parts[0];
    if (op == "QUIT") break;
    if (op == "D" && parts.size() == 3) {
      bridge.comms.Notify(parts[1], std::strtod(parts[2].c_str(), nullptr));
    } else if (op == "S" && parts.size() == 3) {
      bridge.comms.Notify(parts[1], parts[2]);
    } else if (op == "CLOCK" && parts.size() == 2) {
      *clock = std::strtod(parts[1].c_str(), nullptr);
      std::cout << "OK" << std::endl;
    } else if ((op == "REG" || op == "QREG") && parts.size() == 2) {
      std::lock_guard<std::mutex> lock(bridge.mutex);
      bridge.registered.push_back(parts[1]);
      if (op == "QREG") bridge.queued.insert(parts[1]);
      if (bridge.connected) bridge.comms.Register(parts[1], 0);
      std::cout << "OK" << std::endl;
    } else if (op == "CONNECTED" && parts.size() == 2) {
      std::unique_lock<std::mutex> lock(bridge.mutex);
      bool ok = bridge.changed.wait_for(lock, std::chrono::milliseconds(std::atol(parts[1].c_str())), [&] { return bridge.connected; });
      std::cout << (ok ? "OK" : "TIMEOUT") << std::endl;
    } else if (op == "WAITVAL" && parts.size() == 4) {
      const std::string name = parts[1];
      const double bound = std::strtod(parts[2].c_str(), nullptr);
      std::unique_lock<std::mutex> lock(bridge.mutex);
      bool ok = bridge.changed.wait_for(lock, std::chrono::milliseconds(std::atol(parts[3].c_str())), [&] {
        const Latest& entry = bridge.latest[name];
        return entry.count > 0 && entry.is_double && entry.number >= bound;
      });
      std::cout << (ok ? "OK" : "TIMEOUT") << "\t" << bridge.latest[name].count << std::endl;
    } else if (op == "GET" && parts.size() == 2) {
      std::lock_guard<std::mutex> lock(bridge.mutex);
      const Latest& entry = bridge.latest[parts[1]];
      std::cout << entry.count << "\t" << entry.time << "\t" << (entry.is_double ? "D" : "S") << "\t";
      if (entry.is_double)
        std::cout << entry.number;
      else
        std::cout << entry.text;
      std::cout << std::endl;
    } else if (op == "DRAIN" && parts.size() == 2) {
      std::vector<std::string> values;
      {
        std::lock_guard<std::mutex> lock(bridge.mutex);
        values.swap(bridge.queues[parts[1]]);
      }
      std::cout << values.size() << "\n";
      for (const std::string& value : values) std::cout << value << "\n";
      std::cout << std::flush;
    } else {
      std::cout << "ERROR\tbad command: " << single_line(line) << std::endl;
    }
  }
  // No Close(): a MOOS client's close waits in MOOS time, which only this process moves.
  _exit(0);
}
