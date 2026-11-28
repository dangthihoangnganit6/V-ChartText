# Ví dụ trước / sau (A = VLM mô tả trực tiếp, B = pipeline 4 bước)


## Qwen3-VL-2B-Instruct


### bar_007 (bar)

- Nhãn: Lực lượng lao động / 2000: 37.6; Lực lượng lao động / 2005: 44.9; Lực lượng lao động / 2010: 50.4; Lực lượng lao động / 2015: 54.3; Lực lượng lao động / 2019: 55.8; Lực lượng lao động / 2021: 50.6
- **A** (4 số sai / 12): Biểu đồ cột thể hiện **lực lượng lao động** của nước ta từ năm 2000 đến 2021, được đo bằng **triệu người**. Trục hoành là **năm**, trục tung là **lực lượng lao động (triệu người)**. Dữ liệu cho thấy lực lượng lao động tăng dần từ 37,6 triệu người năm 2000 lên 50,6 triệu người năm 2021. Các năm có các giá trị cụ thể: 2000: 37,6 triệu, 2005: 44,9 triệu, 2010: 50,4 triệu, 2015: 54,3 triệu, 2019: 55,8 triệu, 2021: 50,6 triệu. Xu hướng tăng trưởng ổn định, với một giai đoạn tăng mạnh từ 2010 đến 2015, sau đó có sự giảm nhẹ từ 2019 đến 2021. Dữ liệu được lấy từ các năm 2001, 2011, 2016, 2022.
- **B** (0 số sai / 3): Biểu đồ cột thể hiện lực lượng lao động từ 15 tuổi trở lên của nước ta giai đoạn 2000 – 2021, từ 2000 đến 2021. Đơn vị: triệu người. Năm 2000 là 37,6 triệu người, đến 2021 là 50,6 triệu người; cao nhất 55,8 triệu người vào 2019. Giá trị có biến động, không tăng hoặc giảm liên tục.

### combo_012 (combo)

- Nhãn: GDP / 1961: 53.5; GDP / 1970: 212.6; GDP / 1990: 3132.0; GDP / 2000: 4968.4; GDP / 2010: 5759.1; GDP / 2019: 5123.3; GDP / 2020: 5040.1; Tốc độ tăng trưởng GDP / 1961: 12.0; Tốc độ tăng trưởng GDP / 1970: 2.5; Tốc độ tăng trưởng GDP / 1990: 4.8; Tốc độ tăng trưởng GDP / 2000: 2.7; Tốc độ tăng trưởng GDP / 2010: 4.1 ...
- **A** (4 số sai / 13): Biểu đồ thể hiện hiện trạng GDP và tốc độ tăng trưởng GDP của Nhật Bản từ năm 1961 đến 2020. Trục hoành (dọc theo chiều ngang) thể hiện các năm, từ 1961 đến 2020. Trục tung (dọc theo chiều dọc) thể hiện giá trị GDP theo đơn vị Tỉ USD, với các mức từ 0 đến 7000. Trục tung thứ hai thể hiện tốc độ tăng trưởng GDP theo phần trăm (%), với các mức từ -6% đến 14%. 

GDP được thể hiện bằng các thanh màu xanh lá cây, trong đó giá trị năm 1961 là 53,5 Tỉ USD, tăng lên 212,6 Tỉ USD vào năm 1970, rồi đạt đỉnh 3132 Tỉ USD vào năm 1990. Tốc độ tăng trưởng GDP được thể hiện bằng đường kẻ đỏ, với mức tăng trưởng từ 12% vào năm 1961, giảm mạnh xuống 2,5% vào năm 1970, sau đó tăng lên 4,8% vào năm 1990, đạt mức cao nhất 5759,1% vào năm 2010, rồi giảm xuống 0,3% vào năm 2019 và cuối cùng là -4,5% vào năm 2020. 

Tốc độ tăng trưởng GDP có xu hướng giảm mạnh từ năm 2010 đến 2020, cho thấy sự suy giảm trong tăng trưởng kinh tế.
- **B** (0 số sai / 5): Biểu đồ kết hợp cột và đường thể hiện GDP, tốc độ tăng trưởng GDP của Nhật Bản giai đoạn 1961 - 2020. Có hai chuỗi số liệu: GDP (Tỉ USD), Tốc độ tăng trưởng GDP (%); từ 1961 đến 2020. Đơn vị: Tỉ USD và %. GDP (Tỉ USD): năm 1961 là 53,5, đến 2020 là 5.040,1; cao nhất 5.759,1 vào 2010. Tốc độ tăng trưởng GDP (%): năm 1961 là 12, đến 2020 là -4,5. Biểu đồ có hai trục tung với hai đơn vị khác nhau, cần đọc mỗi chuỗi theo trục của nó. Một số giá trị chưa xác minh được từ ảnh nên không đọc ra.

### pie_004 (pie)

- Nhãn: Tỷ lệ trong cơ thể / Các nguyên tố khác: 4.0; Tỷ lệ trong cơ thể / Nitrogen: 3.0; Tỷ lệ trong cơ thể / Hydrogen: 9.5; Tỷ lệ trong cơ thể / Oxygen: 65.0; Tỷ lệ trong cơ thể / Carbon: 18.5
- **A** (4 số sai / 11): Biểu đồ tròn này thể hiện **tỉ lệ khối lượng các nguyên tố trong cơ thể người**. Tiêu đề là: **Tỉ lệ khối lượng các nguyên tố trong cơ thể người**.

- **Các nguyên tố** được phân loại theo màu sắc và biểu tượng:
  - **Carbon (C)**: 65% (màu hình vuông chấm)
  - **Oxygen (O)**: 25% (màu hình vuông chấm)
  - **Hydrogen (H)**: 10% (màu hình vuông chấm)
  - **Nitrogen (N)**: 3% (màu hình vuông chấm)
  - **Các nguyên tố khác**: 4% (màu hình vuông chấm)

- **Xu hướng**: Carbon chiếm tỷ lệ lớn nhất (65%), tiếp theo là oxy (25%), hydrogen (10%), nitơ (3%), và các nguyên tố khác (4%).

- **Nhận xét**: Carbon là nguyên tố chiếm tỷ lệ lớn nhất trong cơ thể người, chiếm 65% khối lượng. Các nguyên tố khác như oxy, hydrogen, nitơ cũng đóng vai trò quan trọng trong cấu trúc và chức năng của cơ thể.
- **B** (0 số sai / 5): Biểu đồ tròn thể hiện tỉ lệ khối lượng các nguyên tố trong cơ thể người. Các thành phần: Các nguyên tố khác, Nitrogen, Hydrogen, Oxygen, Carbon. Đơn vị: %. Oxygen: 65%; Các nguyên tố khác: 18,5%; Hydrogen: 9,5%; Carbon: 4%; Nitrogen: 3%. Oxygen chiếm tỉ trọng lớn nhất, Nitrogen nhỏ nhất.

### area_010 (area)

- Nhãn: Lúa đông xuân / 2005: 40.1; Lúa đông xuân / 2010: 41.2; Lúa đông xuân / 2013: 39.3; Lúa đông xuân / 2016: 39.6; Lúa hè thu và thu đông / 2005: 32.1; Lúa hè thu và thu đông / 2010: 32.5; Lúa hè thu và thu đông / 2013: 35.6; Lúa hè thu và thu đông / 2016: 36.0; Lúa mùa / 2005: 27.8; Lúa mùa / 2010: 26.3; Lúa mùa / 2013: 25.1; Lúa mùa / 2016: 24.4
- **A** (2 số sai / 14): Biểu đồ là biểu đồ cột phân tầng, thể hiện sự chuyển dịch cơ cấu diện tích lúa phân theo mùa vụ của nước ta từ năm 2005 đến 2016. Tiêu đề: "Chuyển dịch cơ cấu diện tích lúa phân theo mùa vụ của nước ta, giai đoạn 2005 - 2016". Trục hoành: Năm, từ 2005 đến 2016. Trục tung: %, từ 0 đến 100. Các loại lúa được biểu thị bằng các kiểu hình: lúa dong xuan (ký hiệu vuông chấm), lúa hè thu và thu đông (ký hiệu vuông chấm), lúa mùa (ký hiệu chấm). Các số liệu chính: Lúa dong xuan: 27,8% (2005), 26,3% (2010), 25,1% (2013), 24,4% (2016). Lúa hè thu và thu đông: 32,1% (2005), 32,5% (2010), 35,6% (2013), 36,0% (2016). Lúa mùa: 40,1% (2005), 41,2% (2010), 39,3% (2013), 39,6% (2016). Từ 2005 đến 2016, diện tích lúa mùa giảm, diện tích lúa dong xuan và lúa hè thu và thu đông tăng.
- **B** (0 số sai / 8): Biểu đồ cột thể hiện chuyển dịch cơ cấu diện tích lúa phân theo mùa vụ của nước ta, giái đoạn 2005 - 2016. Có ba chuỗi số liệu: Lúa đồng xuân, Lúa hè thu và thu đông, Lúa mùa; từ 2005 đến 2016. Đơn vị: %. Lúa đồng xuân: năm 2005 là 27,8%, đến 2016 là 24,4%. Lúa hè thu và thu đông: năm 2005 là 32,1%, đến 2016 là 36%. Lúa mùa: năm 2005 là 40,1%, đến 2016 là 39,6%; cao nhất 41,2% vào 2010; thấp nhất 39,3% vào 2013. Tại 2016, Lúa mùa lớn nhất, Lúa đồng xuân nhỏ nhất. So với đầu kỳ, Lúa hè thu và thu đông tăng nhẹ, còn Lúa đồng xuân giảm nhẹ.

### area_006 (area) (pipeline vẫn sai: lỗi từ bước 1)

- Nhãn: Xuất khẩu / 1985: 39.3; Xuất khẩu / 1995: 53.5; Xuất khẩu / 2004: 51.4; Xuất khẩu / 2012: 53.0; Nhập khẩu / 1985: 60.7; Nhập khẩu / 1995: 46.5; Nhập khẩu / 2004: 48.6; Nhập khẩu / 2012: 47.0
- **A** (4 số sai / 14): Biểu đồ là biểu đồ cột dọc, thể hiện tỷ lệ (%) của các loại sản phẩm xuất khẩu và nhập khẩu từ năm 1985 đến 2012. Tiêu đề: "Tỷ lệ xuất khẩu và nhập khẩu từ năm 1985 đến 2012". Trục hoành: "Năm", từ 1985 đến 2012. Trục tung: "%", từ 0 đến 100. Chú giải: Cột gạch chéo: Xuất khẩu, cột chấm: Nhập khẩu. Các số liệu chính: Năm 1985: Xuất khẩu 30,3%, Nhập khẩu 53,5%. Năm 1995: Xuất khẩu 46,5%, Nhập khẩu 53,5%. Năm 2004: Xuất khẩu 48,6%, Nhập khẩu 51,4%. Năm 2012: Xuất khẩu 47%, Nhập khẩu 53%. Xu hướng: Xuất khẩu tăng từ 30,3% đến 47%, trong khi nhập khẩu tăng từ 53,5% đến 53%. Tuy nhiên, xuất khẩu có xu hướng tăng, nhưng vẫn thấp hơn nhập khẩu.
- **B** (2 số sai / 8): Biểu đồ miền, thể hiện cơ cấu từ 1985 đến 2012. Các thành phần: Xuất khẩu, Nhập khẩu. Đơn vị: %. Năm 1985: Nhập khẩu: 60,7%; Xuất khẩu: 30,3%. Năm 2012: Nhập khẩu: 53%; Xuất khẩu: 47%. Từ 1985 đến 2012, tỉ trọng Xuất khẩu tăng từ 30,3% lên 47%. Tỉ trọng Nhập khẩu giảm từ 60,7% xuống 53%.

## Vintern-1B-v3_5


### combo_004 (combo)

- Nhãn: Dầu thô / 2010: 7555.0; Dầu thô / 2012: 7348.0; Dầu thô / 2013: 7373.0; Dầu thô / 2015: 7517.0; Điện / 2010: 158.0; Điện / 2012: 169.0; Điện / 2013: 169.0; Điện / 2015: 178.0
- **A** (4 số sai / 12): Biểu đồ thể hiện sản lượng dầu thô và điện của Thái Lan trong giai đoạn 2010-2015. Biểu đồ là biểu đồ cột, với trục tung là số nghìn tấn (khoảng 2000, 4000, 6000, 8000), trục hoành là năm (2010, 2012, 2013, 2015). Cột biểu diễn sản lượng dầu thô được tô màu xám, cột biểu diễn sản lượng điện được tô màu đen.  Số liệu chính là số nghìn tấn dầu thô (7555, 7348, 7373, 7517) và số tỷ kWh điện (158, 169, 169, 178). Xu hướng chung là sản lượng điện tăng dần so với sản lượng dầu thô trong giai đoạn này.
- **B** (0 số sai / 5): Biểu đồ cột thể hiện sản lượng dầu thô và sản lượng điện của Thái Lan, giai đoạn 2010 - 2015. Có hai chuỗi số liệu: Dầu thô, Điện; từ 2010 đến 2015. Đơn vị: Nghìn tấn. Dầu thô: năm 2010 là 158 nghìn tấn, đến 2015 là 178 nghìn tấn. Điện: năm 2010 là 7.555 nghìn tấn, đến 2015 là 7.517 nghìn tấn; thấp nhất 7.348 nghìn tấn vào 2012. Tại 2015, Điện lớn nhất, Dầu thô nhỏ nhất. So với đầu kỳ, Dầu thô tăng nhẹ, còn Điện gần như không đổi.

### area_016 (area)

- Nhãn: Nông, lâm, ngư nghiệp / 1991: 40.5; Nông, lâm, ngư nghiệp / 1995: 27.2; Nông, lâm, ngư nghiệp / 2002: 23.0; Nông, lâm, ngư nghiệp / 2010: 21.0; Nông, lâm, ngư nghiệp / 2014: 19.7; Công nghiệp, xây dựng / 1991: 23.8; Công nghiệp, xây dựng / 1995: 28.8; Công nghiệp, xây dựng / 2002: 38.5; Công nghiệp, xây dựng / 2010: 36.7; Công nghiệp, xây dựng / 2014: 36.9; Dịch vụ / 1991: 35.7; Dịch vụ / 1995: 44.0 ...
- **A** (3 số sai / 10): Biểu đồ thể hiện cơ cấu GDP phân theo ngành của nước ta giai đoạn 1991-2014. Biểu đồ là biểu đồ cột, với trục tung thể hiện tỷ lệ phần trăm (0% - 100%), trục hoành thể hiện thời gian (1991, 1995, 2002, 2010, 2014). Các cột biểu diễn tỷ lệ phần trăm của GDP theo từng ngành: Nông, lâm, ngư nghiệp (35,7%), Công nghiệp, xây dựng (38,5%), Dịch vụ (36,7%), và 4 ngành khác (44%, 38,5%, 42,3%, 43,4%).  Các số liệu chính là tỷ lệ phần trăm của GDP theo từng ngành trong giai đoạn 1991-2014. Xu hướng nhận xét: GDP có xu hướng tăng dần theo thời gian, đặc biệt là trong giai đoạn 1995-2002.
- **B** (0 số sai / 6): Biểu đồ cột thể hiện cơ cấu GDP phân theo ngành của nước ta giai đoạn 1991-2014. Có ba chuỗi số liệu: Nông, lâm, ngư nghiệp, Công nghiệp, xây dựng, Dịch vụ; từ 1991 đến 2014. Đơn vị: %. Nông, lâm, ngư nghiệp: năm 1991 là 35,7%, đến 1991 là 35,7%. Công nghiệp, xây dựng: năm 1995 là 44%, đến 2010 là 36,7%. Dịch vụ: năm 2002 là 38,5%, đến 2014 là 36,9%. So với đầu kỳ, Dịch vụ giảm nhẹ, còn Công nghiệp, xây dựng giảm.

### bar_004 (bar)

- Nhãn: Sản lượng thủy sản khai thác / 2000: 4027.4; Sản lượng thủy sản khai thác / 2010: 4075.8; Sản lượng thủy sản khai thác / 2020: 5081.0; Sản lượng thuỷ sản nuôi trồng / 2000: 77.1; Sản lượng thuỷ sản nuôi trồng / 2010: 121.0; Sản lượng thuỷ sản nuôi trồng / 2020: 219.2
- **A** (3 số sai / 6): Biểu đồ là biểu đồ cột thể hiện sản lượng thủy sản của Liên bang Nga từ năm 2000 đến năm 2020. Trục tung thể hiện sản lượng (nghìn tấn), trục hoành thể hiện năm. Biểu đồ có hai cột biểu diễn sản lượng thủy sản khai thác và sản lượng thủy sản nuôi trồng.  Năm 2000, sản lượng thủy sản khai thác là 77,1 nghìn tấn, sản lượng thủy sản nuôi trồng là 4,027,4 nghìn tấn. Năm 2010, sản lượng thủy sản khai thác là 121,0 nghìn tấn, sản lượng thủy sản nuôi trồng là 4,075,8 nghìn tấn. Năm 2020, sản lượng thủy sản khai thác là 219,2 nghìn tấn, sản lượng thủy sản nuôi trồng là 5,081,0 nghìn tấn.  Xu hướng chung là sản lượng thủy sản tăng dần từ năm 2000 đến năm 2020.
- **B** (0 số sai / 4): Biểu đồ cột thể hiện sản lượng thủy sản Liên bang Nga giai đoạn 2000 - 2020. Có hai chuỗi số liệu: Sản lượng thủy sản khai thác, Sản lượng thủy sản nuôi trồng; từ 2000 đến 2020. Không rõ đơn vị. Sản lượng thủy sản khai thác: năm 2000 là 77,1, đến 2020 là 219,2. Sản lượng thủy sản nuôi trồng: năm 2010 là 121, đến 2010 là 121.

### pie_020 (pie)

- Nhãn: Cơ cấu tiêu dùng / Khí: 24.2; Cơ cấu tiêu dùng / Than: 27.0; Cơ cấu tiêu dùng / Năng lượng hạt nhân: 4.3; Cơ cấu tiêu dùng / Thủy điện: 6.4; Cơ cấu tiêu dùng / Năng lượng tái tạo: 5.0; Cơ cấu tiêu dùng / Dầu: 33.1
- **A** (3 số sai / 15): Biểu đồ là biểu đồ tròn, tiêu đề là "Câu 7. Cho biểu đồ biểu diễn cơ cấu tiêu dùng các dạng năng lượng của toàn cầu năm 2019. Biết rằng, năng lượng hóa thạch bao gồm: than, dầu và khí."  Trục x là số liệu (từ 0 đến 100), trục y là các loại năng lượng (khí, than, năng lượng hạt nhân, thủy điện, năng lượng tái tạo, dầu).  Các số liệu chính là: 33.1%, 24.2%, 27%, 5%, 6.4%, 4.3%.  Xu hướng nhận xét: Năng lượng hóa thạch chiếm tỷ lệ cao nhất (33.1%), tiếp theo là than (24.2%), năng lượng hạt nhân (27%), thủy điện (5%), năng lượng tái tạo (6.4%), và dầu (4.3%).
- **B** (0 số sai / 6): Biểu đồ tròn thể hiện cơ cấu tiêu dùng năng lượng. Các thành phần: Khí, Than, Năng lượng hạt nhân, Thủy điện, Năng lượng tái tạo, Dầu. Đơn vị: %. Khí: 33,1%; Năng lượng hạt nhân: 27%; Than: 24,2%; Năng lượng tái tạo: 6,4%; Thủy điện: 5%; Dầu: 4,3%. Khí chiếm tỉ trọng lớn nhất, Dầu nhỏ nhất.

### bar_003 (bar) (pipeline vẫn sai: lỗi từ bước 1)

- Nhãn: GDP / Hoa Kỳ: 20893.7; GDP / Trung Quốc: 14687.7; GDP / Nhật Bản: 5040.1; GDP / Đức: 3846.4; GDP / Anh: 2756.9
- **A** (0 số sai / 5): Biểu đồ là biểu đồ cột thể hiện GDP của các nền kinh tế hàng đầu thế giới năm 2020. Trục tung thể hiện tỷ lệ phần trăm (TT USD), với đơn vị là tỷ. Trục hoành thể hiện tên các nền kinh tế: Hoa Kỳ, Trung Quốc, Nhật Bản, Đức, Anh, Nước. Các cột biểu diễn GDP của mỗi nền kinh tế.  Số liệu chính là: Hoa Kỳ (20.893,7 USD), Trung Quốc (14.687,7 USD), Nhật Bản (5.040,1 USD), Đức (3.846,4 USD), Anh (2.756,9 USD).  Xu hướng nhận xét: Hoa Kỳ có GDP cao nhất, tiếp theo là Trung Quốc, Nhật Bản, Đức, Anh và Nước.
- **B** (1 số sai / 6): Biểu đồ cột thể hiện hình 19.1. GDP của các nền kinh tế hàng đầu thế giới năm 2020, gồm năm nước. Không rõ đơn vị. Cụ thể, Hoa Kỳ là 20.893,7, Trung Quốc là 14.687,7, Nhật Bản là 5.040,1, Đức là 3.846,4 và Anh là 2.756,9. Xếp từ cao xuống thấp: Hoa Kỳ, Trung Quốc, Nhật Bản, Đức và Anh. Hoa Kỳ gấp khoảng tám lần Anh.
