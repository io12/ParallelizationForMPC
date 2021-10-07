// MIT License
//
// Copyright (c) 2019 Oleksandr Tkachenko, Lennart Braun
// Cryptography and Privacy Engineering Group (ENCRYPTO)
// TU Darmstadt, Germany
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

#pragma once

#include <boost/fiber/condition_variable.hpp>
#include <boost/fiber/mutex.hpp>
#include <functional>

namespace encrypto::motion {

/// \brief Wraps a boost::fibers::condition_variable with a boost::fibers::mutex
///        and a condition checking function.
class FiberCondition {
 public:
  ~FiberCondition() = default;
  FiberCondition() = delete;
  FiberCondition(FiberCondition&) = delete;

  /// \brief Registers the condition function that encapsulates the condition checking.
  /// \param condition_function
  FiberCondition(const std::function<bool()> condition_function)
      : condition_function_(condition_function) {}

  // checks if the condition was satisfied
  // bool operator()() {
  //   std::scoped_lock lock(mutex_);
  //   return condition_function_();
  // }

  /// \brief Blocks until fiber is notified and condition_function_ returns true.
  void Wait() const {
    std::unique_lock<decltype(mutex_)> lock(mutex_);
    condition_variable_.wait(lock, condition_function_);
  }

  /// \brief Blocks until fiber is notified and condition_function_ returns true
  ///        or \p duration time has passed.
  template <typename Tick, typename Period>
  bool WaitFor(std::chrono::duration<Tick, Period> duration) const {
    std::unique_lock<decltype(mutex_)> lock(mutex_);
    condition_variable_.wait_for(lock, duration, condition_function_);
    return condition_function_();
  }

  /// \brief Unblocks one thread waiting for condition_variable_.
  void NotifyOne() const noexcept { condition_variable_.notify_one(); }

  /// \brief Unblocks all threads waiting for condition_variable_.
  void NotifyAll() const noexcept { condition_variable_.notify_all(); }

  /// \brief Get the mutex.
  /// \note The variables that the condition function depends on shall
  ///       only be modified under the locked mutex.
  boost::fibers::mutex& GetMutex() noexcept { return mutex_; }

 private:
  mutable boost::fibers::condition_variable condition_variable_;
  mutable boost::fibers::mutex mutex_;
  const std::function<bool()> condition_function_;
};

}  // namespace encrypto::motion
