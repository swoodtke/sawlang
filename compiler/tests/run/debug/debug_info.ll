define internal i64 @"saw panic_lines.crash(n: Int)"(i64 %p1) #0 !dbg !0 {
entry:
  %l0 = alloca i64, align 8
  %l1 = alloca i64, align 8
  %l2 = alloca i8, align 1
  %l3 = alloca i64, align 8
  %l4 = alloca i64, align 8
  %l5 = alloca i64, align 8
  %t12 = alloca [48 x i8], align 8
  store i64 %p1, ptr %l1, !dbg !1
  br label %bb0, !dbg !1
bb0:
  %t0 = load i64, ptr %l1, !dbg !2
  %t1 = icmp sgt i64 %t0, 2, !dbg !2
  %t2 = zext i1 %t1 to i8, !dbg !2
  store i8 %t2, ptr %l2, !dbg !2
  %t3 = load i8, ptr %l2, !dbg !3
  %t4 = icmp ne i8 %t3, 0, !dbg !3
  br i1 %t4, label %bb2, label %bb3, !dbg !3
bb1:
  %t5 = load i64, ptr %l1, !dbg !4
  %t6 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t5, i64 1), !dbg !4
  %t7 = extractvalue { i64, i1 } %t6, 0, !dbg !4
  %t8 = extractvalue { i64, i1 } %t6, 1, !dbg !4
  br i1 %t8, label %check.0, label %checked.1, !dbg !4
check.0:
  call void @__saw_fail_overflow(ptr @.bytes.0, i64 15, i64 7), !dbg !4
  unreachable, !dbg !4
checked.1:
  store i64 %t7, ptr %l3, !dbg !4
  %t9 = load i64, ptr %l3, !dbg !5
  %t10 = call i64 @"saw panic_lines.crash(n: Int)"(i64 %t9), !dbg !5
  store i64 %t10, ptr %l4, !dbg !5
  br label %bb4, !dbg !5
bb2:
  %t11 = load i64, ptr %l1, !dbg !6
  store i64 0, ptr %t12, !dbg !6
  %t13 = getelementptr i8, ptr %t12, i64 8, !dbg !6
  store ptr @.bytes.1, ptr %t13, !dbg !6
  %t14 = getelementptr i8, ptr %t12, i64 16, !dbg !6
  store i64 15, ptr %t14, !dbg !6
  %t15 = getelementptr i8, ptr %t12, i64 24, !dbg !6
  store i64 1, ptr %t15, !dbg !6
  %t16 = getelementptr i8, ptr %t12, i64 32, !dbg !6
  store i64 %t11, ptr %t16, !dbg !6
  call void @__saw_fail_parts(ptr @.bytes.0, i64 15, i64 6, ptr @.bytes.2, i64 0, ptr %t12, i64 2), !dbg !6
  unreachable, !dbg !6
  unreachable, !dbg !6
bb3:
  br label %bb1, !dbg !3
bb4:
  %t17 = load i64, ptr %l4, !dbg !5
  %t18 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t17, i64 1), !dbg !5
  %t19 = extractvalue { i64, i1 } %t18, 0, !dbg !5
  %t20 = extractvalue { i64, i1 } %t18, 1, !dbg !5
  br i1 %t20, label %check.2, label %checked.3, !dbg !5
check.2:
  call void @__saw_fail_overflow(ptr @.bytes.0, i64 15, i64 7), !dbg !5
  unreachable, !dbg !5
checked.3:
  store i64 %t19, ptr %l5, !dbg !5
  %t21 = load i64, ptr %l5, !dbg !5
  store i64 %t21, ptr %l0, !dbg !5
  %t22 = load i64, ptr %l0, !dbg !7
  ret i64 %t22, !dbg !7
}

!0 = distinct !DISubprogram(name: "panic_lines.crash(n: Int)", linkageName: "saw panic_lines.crash(n: Int)", scope: !8, file: !8, line: 5, type: !9, scopeLine: 5, spFlags: DISPFlagDefinition, unit: !10)
!1 = !DILocation(line: 5, column: 1, scope: !0)
!2 = !DILocation(line: 6, column: 8, scope: !0)
!3 = !DILocation(line: 6, column: 5, scope: !0)
!4 = !DILocation(line: 7, column: 11, scope: !0)
!5 = !DILocation(line: 7, column: 5, scope: !0)
!6 = !DILocation(line: 6, column: 16, scope: !0)
!7 = !DILocation(line: 8, column: 1, scope: !0)
!8 = !DIFile(filename: "panic_lines.saw", directory: ".")
!9 = !DISubroutineType(types: !11)
!10 = distinct !DICompileUnit(language: DW_LANG_C99, file: !8, producer: "sawc", isOptimized: false, runtimeVersion: 0, emissionKind: LineTablesOnly)
!11 = !{null}
