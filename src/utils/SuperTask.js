
export class SuperTask {
  constructor(parallelCount = 5) {
    this.parallelCount = parallelCount
    this.tasks = []
    this.runningCount = 0
    this.resolveFinished = null
    this.rejectFinished = null
    this.errors = []
    this.cancelled = false
    this.cancelReason = null
  }

  // 添加单个任务
  add(task) {
    return new Promise((resolve, reject) => {
      this.tasks.push({ task, resolve, reject })
      this._run() // 确保每次添加任务后都尝试运行任务
    })
  }

  // 批量添加任务并开始执行
  setTasks(tasks) {
    tasks.forEach(task => this.add(task))
  }

  // 返回一个 Promise，在所有任务完成后解决或拒绝
  finished() {
    return new Promise((resolve, reject) => {
      if (this.tasks.length === 0 && this.runningCount === 0) {
        if (this.cancelled) {
          reject(this.cancelReason || new Error('cancelled'))
        } else if (this.errors.length > 0) {
          reject(this.errors)
        } else {
          resolve()
        }
      } else {
        this.resolveFinished = resolve
        this.rejectFinished = reject
      }
    })
  }

  cancel(reason = new Error('cancelled')) {
    if (this.cancelled) return
    this.cancelled = true
    this.cancelReason = reason
    this.tasks = []
    if (this.runningCount === 0) {
      if (this.rejectFinished) {
        this.rejectFinished(reason)
      }
    }
  }

  // 执行任务
  _run() {
    while (!this.cancelled && this.runningCount < this.parallelCount && this.tasks.length > 0) {
      const { task, resolve, reject } = this.tasks.shift()
      this.runningCount++
      task()
        .then(resolve)
        .catch(error => {
          this.errors.push(error) // 收集错误
          resolve() // 即使任务失败也标记为完成
        })
        .finally(() => {
          this.runningCount--
          this._checkFinished()
          this._run()
        })
    }
  }

  // 检查所有任务是否完成
  _checkFinished() {
    if (this.tasks.length === 0 && this.runningCount === 0) {
      if (this.cancelled) {
        if (this.rejectFinished) {
          this.rejectFinished(this.cancelReason || new Error('cancelled'))
        }
      } else if (this.errors.length > 0) {
        if (this.rejectFinished) {
          this.rejectFinished(this.errors)
        }
      } else {
        if (this.resolveFinished) {
          this.resolveFinished()
        }
      }
    }
  }
}

