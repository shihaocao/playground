#include <iostream>
#include <vector>
#include <algorithm>
#include <random>
#include <chrono>
#include <thread>
#include "factorial.hpp"

// Forward declarations
int partition_array(std::vector<int>& arr, int low, int high);

void bubble_sort(std::vector<int>& arr) {
    int n = arr.size();
    for (int i = 0; i < n-1; i++) {
        for (int j = 0; j < n-i-1; j++) {
            if (arr[j] > arr[j+1]) {
                std::swap(arr[j], arr[j+1]);
            }
        }
    }
}

void quick_sort(std::vector<int>& arr, int low, int high) {
    if (low < high) {
        int pi = partition_array(arr, low, high);
        quick_sort(arr, low, pi - 1);
        quick_sort(arr, pi + 1, high);
    }
}

int partition_array(std::vector<int>& arr, int low, int high) {
    int pivot = arr[high];
    int i = (low - 1);
    
    for (int j = low; j <= high - 1; j++) {
        if (arr[j] < pivot) {
            i++;
            std::swap(arr[i], arr[j]);
        }
    }
    std::swap(arr[i + 1], arr[high]);
    return (i + 1);
}

void matrix_multiply(const std::vector<std::vector<int>>& a, 
                     const std::vector<std::vector<int>>& b,
                     std::vector<std::vector<int>>& result) {
    int n = a.size();
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            result[i][j] = 0;
            for (int k = 0; k < n; k++) {
                result[i][j] += a[i][k] * b[k][j];
            }
        }
    }
}

void fibonacci_work(int n) {
    if (n <= 1) return;
    fibonacci_work(n-1);
    fibonacci_work(n-2);
}

int main() {
    std::cout << "Starting complex workload...\n";
    
    // Generate random data
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(1, 1000);
    
    // Bubble sort on large array
    std::vector<int> arr1(1000);
    for (auto& x : arr1) x = dis(gen);
    bubble_sort(arr1);
    
    // Quick sort on another array
    std::vector<int> arr2(500);
    for (auto& x : arr2) x = dis(gen);
    quick_sort(arr2, 0, arr2.size()-1);
    
    // Matrix multiplication
    std::vector<std::vector<int>> matrix(50, std::vector<int>(50));
    std::vector<std::vector<int>> result(50, std::vector<int>(50));
    for (auto& row : matrix) {
        for (auto& x : row) x = dis(gen);
    }
    matrix_multiply(matrix, matrix, result);
    
    // Recursive work
    fibonacci_work(25);
    
    // Some factorial calculations
    for (int i = 0; i < 100; i++) {
        factorial(i % 10);
    }
    
    std::cout << "Complex workload complete!\n";
    return 0;
}
