#include <iostream>
#include <cstdlib>
#include "factorial.hpp"

int main(int argc, char** argv) {
	if (argc < 2) {
		std::cerr << "Usage: factorial_cli <n>\n";
		return 1;
	}
	int n = std::atoi(argv[1]);
	try {
		std::cout << factorial(n) << "\n";
		return 0;
	} catch (const std::exception& e) {
		std::cerr << "Error: " << e.what() << "\n";
		return 2;
	}
}


