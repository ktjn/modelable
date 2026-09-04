(module
  (memory (export "memory") 1)
  (global (export "result_len") (mut i32) (i32.const 0))
  (func (export "alloc") (param i32) (result i32)
    i32.const 1024
  )
  (func (export "run") (param i32 i32) (result i32)
    i32.const RESULT_LEN
    global.set 0
    i32.const 16
  )
  (data (i32.const 16) "{\"$schema\":\"modelable.extension-host/v1\",\"kind\":\"extension_result\",\"status\":\"ok\",\"artifacts\":[{\"path\":\"reference.txt\",\"media_type\":\"text/plain\",\"content\":\"reference extension\"}],\"diagnostics\":[],\"compatibility_findings\":[]}")
)
