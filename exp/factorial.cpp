#include "factorial.hpp"

long long factorial(int n) {
	if (n < 0) {
		throw std::invalid_argument("n must be non-negative");
	}
	long long result = 1;
	for (int i = 2; i <= n; ++i) {
		result *= i;
	}
	return result;
}



