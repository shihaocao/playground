###############################################################################
# Simple C++ Makefile for the `exp` experiments
# - Common sources live flat inside `exp/`
# - Executable entry points (with main) live in `exp/targets/` (optional)
# - A convenience `bin/main` is built from `exp/main.cpp` if present
###############################################################################

CXX ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -pedantic -Iexp -MMD -MP

SRC_DIR := exp
TARGETS_DIR := $(SRC_DIR)/targets
BUILD_DIR := build
BIN_DIR := bin

# Common sources: all .cpp directly under exp/ except the top-level main.cpp
COMMON_SRCS := $(filter-out $(SRC_DIR)/main.cpp,$(wildcard $(SRC_DIR)/*.cpp))
COMMON_OBJS := $(patsubst $(SRC_DIR)/%.cpp,$(BUILD_DIR)/%.o,$(COMMON_SRCS))
COMMON_DEPS := $(COMMON_OBJS:.o=.d)

# Targets built from files in exp/targets/*.cpp → bin/<name>
APP_SOURCES := $(wildcard $(TARGETS_DIR)/*.cpp)
APPS := $(patsubst $(TARGETS_DIR)/%.cpp,$(BIN_DIR)/%,$(APP_SOURCES))

# Optional top-level main built from exp/main.cpp → bin/main if file exists
MAIN_SRC := $(SRC_DIR)/main.cpp
MAIN_BIN := $(BIN_DIR)/main

.PHONY: all clean list run

ifeq (,$(wildcard $(MAIN_SRC)))
all: $(APPS)
else
all: $(MAIN_BIN) $(APPS)
endif

list:
	@echo "Common sources:" $(COMMON_SRCS)
	@echo "App sources:" $(APP_SOURCES)
	@echo "Apps:" $(APPS)
	@echo "Main present:" $(wildcard $(MAIN_SRC))

# Build rules
$(BUILD_DIR)/%.o: $(SRC_DIR)/%.cpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(BIN_DIR)/%: $(TARGETS_DIR)/%.cpp $(COMMON_OBJS) | $(BIN_DIR)
	$(CXX) $(CXXFLAGS) $< $(COMMON_OBJS) -o $@

$(MAIN_BIN): $(MAIN_SRC) $(COMMON_OBJS) | $(BIN_DIR)
	$(CXX) $(CXXFLAGS) $(MAIN_SRC) $(COMMON_OBJS) -o $@

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)

$(BIN_DIR):
	@mkdir -p $(BIN_DIR)

clean:
	rm -rf $(BUILD_DIR) $(BIN_DIR)

# Convenience run (uses bin/main if present)
run: all
ifeq (,$(wildcard $(MAIN_SRC)))
	@echo "No $(MAIN_SRC) found; nothing to run."
else
	$(BIN_DIR)/main
endif

-include $(COMMON_DEPS)



