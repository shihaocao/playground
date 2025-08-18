#include <iostream>
#include <fstream>
#include <string>
#include "factorial.hpp"

int main() {
	std::ifstream in("inputs/factorial_in.txt");
	if (!in) {
		std::cerr << "Error: cannot open inputs/factorial_in.txt\n";
		return 1;
	}
	long long n = 0;
	if (!(in >> n)) {
		std::cerr << "Error: failed to read integer from inputs/factorial_in.txt\n";
		return 2;
	}
	try {
		std::cout << factorial(static_cast<int>(n)) << "\n";
		return 0;
	} catch (const std::exception& e) {
		std::cerr << "Error: " << e.what() << "\n";
		return 3;
	}
}